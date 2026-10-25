import asyncio
import unittest
from typing import Any, cast
from unittest import mock

from ctfbot.errors import ExternalAPIError
from ctfbot.features.tts import engine as engine_module
from ctfbot.features.tts.engine import VoicevoxEngine

CONTAINER = "voicevox"
IDLE = 300.0


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds
        await asyncio.sleep(0)


class FakeProcess:
    def __init__(self, returncode: int, stderr: bytes) -> None:
        self.returncode = returncode
        self.stderr = stderr

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", self.stderr


class HangingProcess:
    returncode = None

    def __init__(self) -> None:
        self.kill = mock.Mock()
        self.wait = mock.AsyncMock()

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.sleep(10)
        return b"", b""


class EngineTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.clock = FakeClock()
        self.podman_calls: list[tuple[str, ...]] = []
        self.podman_result = FakeProcess(0, b"")
        self.podman_gate: asyncio.Event | None = None
        self.client = mock.Mock()
        self.client.check_version.return_value = None
        self.client.synthesize.return_value = b"RIFFdata"

        async def create(*args: Any, **_: Any) -> FakeProcess:
            self.podman_calls.append(tuple(args))
            if self.podman_gate is not None:
                await self.podman_gate.wait()
            return self.podman_result

        patcher = mock.patch.object(
            engine_module.asyncio, "create_subprocess_exec", side_effect=create
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine = self.make_engine(CONTAINER)

    async def asyncTearDown(self) -> None:
        task = self.engine.idle_task
        if task is not None:
            task.cancel()

    def make_engine(self, container: str) -> VoicevoxEngine:
        return VoicevoxEngine(
            self.client,
            container,
            idle_seconds=IDLE,
            ready_timeout=30.0,
            clock=self.clock,
            sleep=self.clock.sleep,
        )

    def actions(self) -> list[str]:
        return [call[1] for call in self.podman_calls]

    async def settle(self) -> None:
        for _ in range(20):
            await asyncio.sleep(0)

    async def let_idle_pass(self) -> None:
        # The fake sleep jumps the clock, so one settle runs the whole timer
        await self.settle()

    async def test_first_call_starts_container_and_waits_for_ready(self) -> None:
        self.client.check_version.side_effect = [
            ExternalAPIError("down"),
            ExternalAPIError("down"),
            None,
        ]
        result = await self.engine.call(self.client.synthesize, "a", 1)
        self.assertEqual(result, b"RIFFdata")
        self.assertEqual(self.podman_calls, [("podman", "start", CONTAINER)])
        self.assertEqual(self.client.check_version.call_count, 3)

    async def test_running_engine_is_not_started_again(self) -> None:
        await self.engine.call(self.client.synthesize, "a", 1)
        await self.engine.call(self.client.synthesize, "b", 1)
        self.assertEqual(self.actions().count("start"), 1)

    async def test_concurrent_first_calls_start_once(self) -> None:
        await asyncio.gather(
            *(self.engine.call(self.client.synthesize, "a", 1) for _ in range(3))
        )
        self.assertEqual(self.actions().count("start"), 1)

    async def test_ready_timeout_fails_like_an_engine_failure(self) -> None:
        self.client.check_version.side_effect = ExternalAPIError("down")
        with self.assertRaises(ExternalAPIError):
            await self.engine.call(self.client.synthesize, "a", 1)
        self.client.synthesize.assert_not_called()
        self.assertFalse(self.engine.running)
        # The next call tries again from the start
        self.client.check_version.side_effect = None
        await self.engine.call(self.client.synthesize, "a", 1)
        self.assertEqual(self.actions(), ["start", "start"])

    async def test_podman_failures_are_logged_and_raised(self) -> None:
        self.podman_result = FakeProcess(1, b"Error: No such container: voicevox\n")
        with (
            self.assertLogs("ctfbot", "WARNING") as logs,
            self.assertRaises(ExternalAPIError),
        ):
            await self.engine.call(self.client.synthesize, "a", 1)
        self.assertIn("No such container", logs.output[0])
        self.client.check_version.assert_not_called()

    async def test_missing_podman_binary_is_an_engine_failure(self) -> None:
        with (
            mock.patch.object(
                engine_module.asyncio,
                "create_subprocess_exec",
                side_effect=FileNotFoundError("podman"),
            ),
            self.assertLogs("ctfbot", "WARNING"),
            self.assertRaises(ExternalAPIError),
        ):
            await self.engine.call(self.client.synthesize, "a", 1)

    async def test_podman_timeout_is_an_engine_failure(self) -> None:
        process = HangingProcess()
        self.podman_result = cast(Any, process)
        with (
            mock.patch.object(engine_module, "PODMAN_TIMEOUT_SECONDS", 0.01),
            self.assertLogs("ctfbot", "WARNING") as logs,
            self.assertRaises(ExternalAPIError),
        ):
            await self.engine.call(self.client.synthesize, "a", 1)
        self.assertIn("timed out", logs.output[0])
        process.kill.assert_called_once()

    async def test_failed_call_forgets_running_so_next_use_restarts(self) -> None:
        await self.engine.call(self.client.synthesize, "a", 1)
        self.client.synthesize.side_effect = [ExternalAPIError("refused"), b"RIFF"]
        with self.assertRaises(ExternalAPIError):
            await self.engine.call(self.client.synthesize, "b", 1)
        await self.engine.call(self.client.synthesize, "c", 1)
        self.assertEqual(self.actions(), ["start", "start"])

    async def test_stops_after_idle_time(self) -> None:
        await self.engine.call(self.client.synthesize, "a", 1)
        await self.let_idle_pass()
        self.assertEqual(self.actions(), ["start", "stop"])
        self.assertGreaterEqual(self.clock.now, 1000.0 + IDLE)
        self.assertFalse(self.engine.running)

    async def test_does_not_stop_while_a_session_holds_it(self) -> None:
        self.engine.hold()
        await self.engine.call(self.client.synthesize, "a", 1)
        await self.let_idle_pass()
        self.clock.now += IDLE * 10
        await self.engine.call(self.client.synthesize, "b", 1)
        await self.let_idle_pass()
        self.assertEqual(self.actions(), ["start"])

    async def test_stop_is_timed_from_session_release(self) -> None:
        self.engine.hold()
        await self.engine.call(self.client.synthesize, "a", 1)
        await self.let_idle_pass()
        self.clock.now += IDLE * 10
        self.engine.release()
        # Idle time counts from the release, not from the last call
        self.assertEqual(self.actions(), ["start"])
        await self.let_idle_pass()
        self.assertEqual(self.actions(), ["start", "stop"])
        self.assertGreaterEqual(self.clock.now, 1000.0 + IDLE * 11)

    async def test_does_not_stop_while_a_call_is_running(self) -> None:
        await self.engine.call(self.client.synthesize, "a", 1)
        release = asyncio.Event()
        started = asyncio.Event()
        loop = asyncio.get_running_loop()

        def blocking() -> None:
            loop.call_soon_threadsafe(started.set)
            asyncio.run_coroutine_threadsafe(release.wait(), loop).result()

        task = asyncio.create_task(self.engine.call(blocking))
        await started.wait()
        self.clock.now += IDLE * 10
        await self.settle()
        self.assertEqual(self.actions(), ["start"])
        release.set()
        await task
        await self.let_idle_pass()
        self.assertEqual(self.actions(), ["start", "stop"])

    async def test_call_during_stop_waits_and_starts_again(self) -> None:
        await self.engine.call(self.client.synthesize, "a", 1)
        self.podman_gate = asyncio.Event()
        await self.settle()
        self.assertEqual(self.actions(), ["start", "stop"])
        call = asyncio.create_task(self.engine.call(self.client.synthesize, "b", 1))
        await self.settle()
        self.assertFalse(call.done())
        self.assertEqual(self.actions(), ["start", "stop"])
        self.podman_gate.set()
        await call
        self.assertEqual(self.actions(), ["start", "stop", "start"])

    async def test_call_arriving_while_stop_waits_for_the_lock_cancels_it(
        self,
    ) -> None:
        await self.engine.call(self.client.synthesize, "a", 1)
        async with self.engine.lock:
            await self.settle()
            self.engine.active += 1
        await self.settle()
        self.engine.active -= 1
        self.assertEqual(self.actions(), ["start"])

    async def test_start_idle_watch_stops_a_container_left_by_a_previous_run(
        self,
    ) -> None:
        self.engine.start_idle_watch()
        await self.let_idle_pass()
        self.assertEqual(self.actions(), ["stop"])

    async def test_shutdown_stops_and_ignores_podman_failure(self) -> None:
        await self.engine.call(self.client.synthesize, "a", 1)
        self.podman_result = FakeProcess(1, b"boom")
        with self.assertLogs("ctfbot", "WARNING"):
            await self.engine.shutdown()
        self.assertEqual(self.actions(), ["start", "stop"])


if __name__ == "__main__":
    unittest.main()
