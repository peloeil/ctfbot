from __future__ import annotations

import datetime

import discord
from discord.ext import commands

from .cogs_loader import load_cogs
from .config import Settings, load_settings
from .discord_gateway import DiscordGateway
from .runtime import BotRuntime, build_runtime
from .utils.helpers import configure_logging, logger, send_interaction_message


class CTFBot(commands.Bot):
    def __init__(self, runtime: BotRuntime) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=runtime.settings.command_prefix, intents=intents
        )
        self.runtime = runtime
        self.settings = runtime.settings
        self.gateway = DiscordGateway(self, logger)
        self._has_announced_ready = False
        self._last_disconnect_at: datetime.datetime | None = None

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
            downtime = now - self._last_disconnect_at
            await self._send_status_message(
                f"🟢 ctfbot reconnected (downtime {int(downtime.total_seconds())}s)"
            )
        self._last_disconnect_at = None

    async def on_disconnect(self) -> None:
        self._last_disconnect_at = datetime.datetime.now(self.settings.tzinfo)
        logger.warning("Disconnected at %s", self._last_disconnect_at.isoformat())

    async def close(self) -> None:
        if not self.is_closed():
            now = datetime.datetime.now(self.settings.tzinfo)
            await self._send_status_message(
                f"🔴 ctfbot disconnecting at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
        await super().close()

    async def _send_status_message(self, content: str) -> None:
        channel = await self.gateway.resolve_messageable_channel(
            self.settings.bot_status_channel_id
        )
        if channel is None:
            return
        await channel.send(content)


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


async def run_bot(bot: CTFBot) -> None:
    await bot.start(bot.settings.discord_token)
