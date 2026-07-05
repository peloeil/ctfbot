import asyncio
import json

import discord
from discord.ext import commands

from bot.errors import RepositoryError
from bot.log import logger
from bot.runtime import get_runtime


class AuditLog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        runtime = get_runtime(bot)
        self.bot = bot
        self.settings = runtime.settings
        self.db = runtime.db

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        changes_json = json.dumps(
            {
                "before": dict(entry.changes.before),
                "after": dict(entry.changes.after),
            },
            default=str,
            ensure_ascii=False,
        )
        try:
            await asyncio.to_thread(
                self.db.insert_audit_log_entry,
                entry_id=entry.id,
                guild_id=entry.guild.id,
                action=entry.action.name,
                user_id=entry.user_id,
                target_id=getattr(entry.target, "id", None),
                reason=entry.reason,
                changes_json=changes_json,
                extra_text=str(entry.extra) if entry.extra is not None else None,
                created_at_unix=int(entry.created_at.timestamp()),
            )
        except RepositoryError as exc:
            logger.error("Failed to save audit log entry %s: %s", entry.id, exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AuditLog(bot))
