import datetime
import signal
from collections.abc import Callable
from types import FrameType
from typing import cast

import discord
from discord.ext import commands

from bot.cogs_loader import load_cogs
from bot.config import Settings, load_settings
from bot.db import Database
from bot.helpers import resolve_messageable, send_interaction, send_safely
from bot.log import configure_logging, logger
from bot.runtime import BotRuntime


class CTFBot(commands.Bot):
    def __init__(self, runtime: BotRuntime) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.runtime = runtime
        self._has_announced_ready = False
        self._shutdown_requested_by_sigint = False

    async def setup_hook(self) -> None:
        await load_cogs(self)
        guild = discord.Object(id=self.runtime.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        # 過去に登録したグローバルコマンドを空の sync で削除する
        # (guild 登録との二重表示防止)
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        logger.info("Synced %s command(s) to guild %s", len(synced), guild.id)

    async def on_ready(self) -> None:
        if self.user is None:
            return
        logger.info("%s has connected to Discord!", self.user)
        if not self._has_announced_ready:
            now = datetime.datetime.now(self.runtime.settings.tzinfo)
            await self._send_status(
                f"🟢 ctfbot connected at {now:%Y-%m-%d %H:%M:%S %Z}"
            )
            self._has_announced_ready = True

    async def close(self) -> None:
        if self._shutdown_requested_by_sigint and not self.is_closed():
            now = datetime.datetime.now(self.runtime.settings.tzinfo)
            await self._send_status(
                f"🔴 ctfbot disconnecting at {now:%Y-%m-%d %H:%M:%S %Z}"
            )
        await super().close()

    def mark_shutdown_requested(self) -> None:
        self._shutdown_requested_by_sigint = True

    async def _send_status(self, content: str) -> None:
        ch = await resolve_messageable(
            self, self.runtime.settings.bot_status_channel_id
        )
        if ch is not None:
            await send_safely(ch, content)


def create_bot(settings: Settings | None = None) -> CTFBot:
    loaded = settings or load_settings()
    configure_logging(loaded.log_level)
    db = Database(loaded.database_path)
    runtime = BotRuntime(settings=loaded, db=db)
    bot = CTFBot(runtime)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, discord.app_commands.CommandOnCooldown):
            await send_interaction(interaction, "コマンドはクールダウン中です。")
            return
        if isinstance(error, discord.app_commands.MissingPermissions):
            await send_interaction(
                interaction, "このコマンドを実行する権限がありません。"
            )
            return
        name = interaction.command.name if interaction.command else "<unknown>"
        logger.error("Unhandled error in /%s: %s", name, error)
        await send_interaction(interaction, "コマンド実行中にエラーが発生しました。")

    return bot


def run_bot(bot: CTFBot) -> None:
    previous = signal.getsignal(signal.SIGINT)

    def handle_sigint(signum: int, frame: FrameType | None) -> None:
        bot.mark_shutdown_requested()
        if previous is signal.SIG_IGN:
            return
        if previous is not signal.SIG_DFL:
            cast(Callable, previous)(signum, frame)
            return
        signal.default_int_handler(signum, frame)

    signal.signal(signal.SIGINT, handle_sigint)
    try:
        bot.run(bot.runtime.settings.discord_token, log_handler=None)
    finally:
        signal.signal(signal.SIGINT, previous)
