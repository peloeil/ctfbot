import asyncio
import json

import discord
from discord.ext import commands

from bot.helpers import fetch_member, sanitize_audit_text, send_audit_message
from bot.log import logger
from bot.runtime import get_runtime

# 対象表記の決定 (docs/features/audit-log.md「Embed / メッセージ形式」)


def _target_name(entry: discord.AuditLogEntry) -> str | None:
    for source in (entry.target, entry.changes.after, entry.changes.before):
        name = getattr(source, "name", None)
        if name is not None:
            return sanitize_audit_text(name)
    return None


def _format_target_line(entry: discord.AuditLogEntry, target_id: int) -> str:
    target_type = entry.action.target_type
    # message の entry.target は対象メッセージの作者
    if target_type in ("user", "message"):
        return f"- 対象: <@{target_id}>"
    if target_type in ("channel", "thread"):
        return f"- 対象: <#{target_id}>"
    if target_type == "role":
        return f"- 対象: <@&{target_id}>"
    name = _target_name(entry)
    if name is None:
        return f"- 対象 ID: {target_id}"
    if target_type == "emoji":
        return f"- 対象: :{name}:"
    return f"- 対象: {name}"


def _message_jump_url(entry: discord.AuditLogEntry) -> str | None:
    message_id = getattr(entry.extra, "message_id", None)
    channel_id = getattr(getattr(entry.extra, "channel", None), "id", None)
    if message_id is None or channel_id is None:
        return None
    return f"https://discord.com/channels/{entry.guild.id}/{channel_id}/{message_id}"


class AuditLog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        runtime = get_runtime(bot)
        self.bot = bot
        self.settings = runtime.settings
        self.db = runtime.db

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        try:
            changes_json = json.dumps(
                {
                    "before": dict(entry.changes.before),
                    "after": dict(entry.changes.after),
                },
                default=str,
                ensure_ascii=False,
            )
            inserted = await asyncio.to_thread(
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
            if inserted:
                await self._notify_admin_action(entry)
        except Exception as exc:
            logger.error("Failed to save audit log entry %s: %s", entry.id, exc)

    async def _notify_admin_action(self, entry: discord.AuditLogEntry) -> None:
        admin_role_id = self.settings.admin_role_id
        if admin_role_id is None or entry.user_id is None:
            return
        member = await fetch_member(entry.guild, entry.user_id)
        if member is None:
            return
        if not any(role.id == admin_role_id for role in member.roles):
            return
        lines = [
            f"🛡️ <@{entry.user_id}> が管理者操作 `{entry.action.name}` を実行しました。"
        ]
        target_id = getattr(entry.target, "id", None)
        if target_id is not None:
            lines.append(_format_target_line(entry, target_id))
        jump_url = _message_jump_url(entry)
        if jump_url is not None:
            lines.append(f"- メッセージ: {jump_url}")
        if entry.reason is not None:
            lines.append(f"- 理由: {sanitize_audit_text(entry.reason)}")
        await send_audit_message(self.bot, lines)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AuditLog(bot))
