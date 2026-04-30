from __future__ import annotations

import datetime
import signal
import time
from collections.abc import Callable
from types import FrameType
from typing import cast

import discord
from discord.ext import commands

from .cogs_loader import load_cogs
from .config import Settings, load_settings
from .discord_gateway import DiscordGateway
from .log import configure_logging, logger
from .runtime import BotRuntime, build_runtime
from .utils.helpers import send_interaction_message

SigintHandler = Callable[[int, FrameType | None], object]


class CTFBot(commands.Bot):
    def __init__(self, runtime: BotRuntime) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.runtime = runtime
        self.settings = runtime.settings
        self.gateway = DiscordGateway(self, logger)
        self._has_announced_ready = False
        self._is_closing = False
        self._last_disconnect_at: datetime.datetime | None = None
        self._last_disconnect_monotonic_ns: int | None = None
        self._shutdown_requested_by_sigint = False

    async def setup_hook(self) -> None:
        await load_cogs(self)
        synced = await self.tree.sync()
        logger.info("Synced %s command(s)", len(synced))

    async def on_ready(self) -> None:
        if self.user is None:
            logger.warning("on_ready called but bot user is not available")
            return

        logger.info("%s has connected to Discord!", self.user)

        now = datetime.datetime.now(self.settings.tzinfo)
        if not self._has_announced_ready:
            await self._send_status_message(
                f"🟢 ctfbot connected at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
            self._has_announced_ready = True
        elif self._last_disconnect_at is not None:
            if self._last_disconnect_monotonic_ns is None:
                logger.warning(
                    "Reconnect event received without monotonic disconnect timestamp"
                )
                downtime_seconds = 0
            else:
                downtime_seconds = max(
                    0,
                    (time.monotonic_ns() - self._last_disconnect_monotonic_ns)
                    // 1_000_000_000,
                )
            await self._send_status_message(
                f"🟢 ctfbot reconnected (downtime {downtime_seconds}s)"
            )
        self._last_disconnect_at = None
        self._last_disconnect_monotonic_ns = None

    async def on_disconnect(self) -> None:
        if self._last_disconnect_at is not None:
            logger.warning(
                "Disconnect event received while already disconnected since %s",
                self._last_disconnect_at.isoformat(),
            )
            return

        now = datetime.datetime.now(self.settings.tzinfo)
        self._last_disconnect_at = now
        self._last_disconnect_monotonic_ns = time.monotonic_ns()
        logger.warning("Disconnected at %s", now.isoformat())

    async def close(self) -> None:
        self._is_closing = True
        if self._shutdown_requested_by_sigint and not self.is_closed():
            now = datetime.datetime.now(self.settings.tzinfo)
            await self._send_status_message(
                f"🔴 ctfbot disconnecting at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
        await super().close()

    def mark_shutdown_requested_by_sigint(self) -> None:
        self._shutdown_requested_by_sigint = True

    async def _send_status_message(self, content: str) -> None:
        channel = await self.gateway.resolve_messageable_channel(
            self.settings.bot_status_channel_id
        )
        if channel is None:
            return
        try:
            await channel.send(content)
        except discord.Forbidden, discord.HTTPException:
            logger.exception("Failed to send status message")


def create_bot(settings: Settings | None = None) -> CTFBot:
    loaded_settings = settings or load_settings()
    configure_logging(loaded_settings.log_level)
    runtime = build_runtime(loaded_settings)
    bot = CTFBot(runtime)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: discord.app_commands.AppCommandError
    ) -> None:
        if isinstance(error, discord.app_commands.CommandOnCooldown):
            await send_interaction_message(
                interaction,
                "コマンドはクールダウン中です。しばらく待ってから再実行してください。",
                ephemeral=True,
            )
            return
        if isinstance(error, discord.app_commands.MissingPermissions):
            await send_interaction_message(
                interaction,
                "このコマンドを実行する権限がありません。",
                ephemeral=True,
            )
            return

        command_name = interaction.command.name if interaction.command else "<unknown>"
        logger.error("Unhandled app command error in %s: %s", command_name, error)
        await send_interaction_message(
            interaction, "コマンド実行中にエラーが発生しました。", ephemeral=True
        )

    return bot


def run_bot(bot: CTFBot) -> None:
    previous_sigint_handler = signal.getsignal(signal.SIGINT)

    def handle_sigint(_signum: int, frame: FrameType | None) -> None:
        bot.mark_shutdown_requested_by_sigint()
        if previous_sigint_handler is signal.SIG_IGN:
            return
        if previous_sigint_handler is not signal.SIG_DFL:
            previous_handler = cast(SigintHandler, previous_sigint_handler)
            previous_handler(signal.SIGINT, frame)
            return
        signal.default_int_handler(signal.SIGINT, frame)

    signal.signal(signal.SIGINT, handle_sigint)
    try:
        bot.run(bot.settings.discord_token, log_handler=None)
    finally:
        signal.signal(signal.SIGINT, previous_sigint_handler)
