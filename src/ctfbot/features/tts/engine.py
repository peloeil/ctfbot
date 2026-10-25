import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable

from ctfbot.errors import ExternalAPIError
from ctfbot.features.tts.voicevox import VoicevoxClient
from ctfbot.log import logger

IDLE_STOP_SECONDS = 300.0
READY_TIMEOUT_SECONDS = 30.0
READY_POLL_SECONDS = 0.2
PODMAN_TIMEOUT_SECONDS = 30.0
MAX_STDERR_CHARS = 200


class VoicevoxEngine:
    """Calls to the ENGINE, starting and stopping its podman container on demand."""

    def __init__(
        self,
        client: VoicevoxClient,
        container: str,
        *,
        idle_seconds: float = IDLE_STOP_SECONDS,
        ready_timeout: float = READY_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
    ) -> None:
        self.client = client
        self.container = container
        self.idle_seconds = idle_seconds
        self.ready_timeout = ready_timeout
        self.clock = clock
        self.sleep = sleep
        # Serializes start and stop so they never interleave
        self.lock = asyncio.Lock()
        # Whether the ENGINE is believed to be up; dropped when a call fails
        self.running = False
        self.holds = 0
        self.active = 0
        self.last_used = clock()
        self.idle_task: asyncio.Task[None] | None = None

    def hold(self) -> None:
        """Keep the ENGINE up until a matching release (a TTS session)."""
        self.holds += 1

    def release(self) -> None:
        self.holds -= 1
        self._touch()

    def start_idle_watch(self) -> None:
        """Stop a container left running by a previous process if it goes unused."""
        self._touch()

    async def shutdown(self) -> None:
        task, self.idle_task = self.idle_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        async with self.lock:
            self.running = False
            await self._stop()

    async def call[**P, R](
        self, func: Callable[P, R], *args: P.args, **kwargs: P.kwargs
    ) -> R:
        """Run a blocking client call in a thread, with the ENGINE up."""
        self.active += 1
        try:
            await self._ensure_running()
            try:
                return await asyncio.to_thread(func, *args, **kwargs)
            except ExternalAPIError:
                # The container may have been stopped from outside
                self.running = False
                raise
        finally:
            self.active -= 1
            self._touch()

    def _touch(self) -> None:
        self.last_used = self.clock()
        if self.idle_task is None or self.idle_task.done():
            self.idle_task = asyncio.create_task(self._idle_loop())

    async def _ensure_running(self) -> None:
        if self.running:
            return
        async with self.lock:
            if self.running:
                return
            await self._podman("start")
            await self._wait_ready()
            self.running = True

    async def _wait_ready(self) -> None:
        deadline = self.clock() + self.ready_timeout
        while True:
            try:
                await asyncio.to_thread(self.client.check_version)
                return
            except ExternalAPIError:
                if self.clock() >= deadline:
                    logger.warning("VOICEVOX did not become ready after podman start")
                    raise
            await self.sleep(READY_POLL_SECONDS)

    async def _idle_loop(self) -> None:
        # Re-armed by _touch whenever a hold or call ends, so it simply exits
        # while the ENGINE is in use
        while True:
            if self.holds or self.active:
                return
            remaining = self.last_used + self.idle_seconds - self.clock()
            if remaining > 0:
                await self.sleep(remaining)
            elif await self._stop_if_idle():
                return

    async def _stop_if_idle(self) -> bool:
        async with self.lock:
            # Re-check: a call may have arrived while waiting for the lock
            if (
                self.holds
                or self.active
                or self.clock() - self.last_used < self.idle_seconds
            ):
                return False
            # Cleared before the await so a call arriving mid-stop waits on the
            # lock and starts the container again
            self.running = False
            await self._stop()
            return True

    async def _stop(self) -> None:
        with contextlib.suppress(ExternalAPIError):
            await self._podman("stop")

    async def _podman(self, action: str) -> None:
        """Run `podman <action> <container>`; failures are logged and raised."""
        try:
            await self._run_podman(action)
        except ExternalAPIError as exc:
            logger.warning("%s", exc)
            raise

    async def _run_podman(self, action: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                "podman",
                action,
                self.container,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise ExternalAPIError(f"podman {action} could not run: {exc}") from exc
        try:
            async with asyncio.timeout(PODMAN_TIMEOUT_SECONDS):
                _, stderr = await process.communicate()
        except TimeoutError:
            raise ExternalAPIError(f"podman {action} timed out") from None
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        if process.returncode != 0:
            summary = stderr.decode(errors="replace").strip()[-MAX_STDERR_CHARS:]
            raise ExternalAPIError(
                f"podman {action} exited with {process.returncode}: {summary}"
            )
