import datetime

import discord
from discord.ext import commands

from .cogs_loader import load_cogs
from .config import settings
from .utils.helpers import configure_logging, logger, send_interaction_message


class CTFBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=settings.command_prefix, intents=intents)
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

        now = datetime.datetime.now(settings.tzinfo)
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
        self._last_disconnect_at = datetime.datetime.now(settings.tzinfo)
        logger.warning("Disconnected at %s", self._last_disconnect_at.isoformat())

    async def close(self) -> None:
        if not self.is_closed():
            now = datetime.datetime.now(settings.tzinfo)
            await self._send_status_message(
                f"🔴 ctfbot disconnecting at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
            )
        await super().close()

    async def _send_status_message(self, content: str) -> None:
        channel_id = settings.bot_status_channel_id
        if channel_id <= 0:
            return

        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.exception("Failed to resolve status channel %s", channel_id)
                return

        if not isinstance(channel, discord.abc.Messageable):
            logger.warning("Status channel %s is not messageable", channel_id)
            return
        await channel.send(content)


def create_bot() -> commands.Bot:
    configure_logging(settings.log_level)
    bot = CTFBot()

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


async def run_bot(bot: commands.Bot) -> None:
    await bot.start(settings.discord_token)
