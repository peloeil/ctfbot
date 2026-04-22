from __future__ import annotations

from collections.abc import Sequence

import discord
from discord.ext import commands

from .discord_gateway import DiscordGateway
from .log import logger
from .utils.helpers import send_message_safely

MAX_AUDIT_MESSAGE_LENGTH = 1900
TRUNCATION_SUFFIX = "..."


def sanitize_audit_text(value: object) -> str:
    normalized = " ".join(str(value).split())
    mention_safe = discord.utils.escape_mentions(normalized)
    mention_safe = mention_safe.replace("<@", "<@\u200b").replace("<#", "<#\u200b")
    return discord.utils.escape_markdown(mention_safe, as_needed=True)


class CommandAuditLogger:
    def __init__(
        self,
        bot: commands.Bot,
        *,
        channel_id: int | None = None,
    ) -> None:
        self._bot = bot
        self._channel_id = channel_id
        self._gateway = DiscordGateway(bot, logger)

    def _resolve_channel_id(self) -> int:
        if self._channel_id is not None:
            return self._channel_id

        runtime = getattr(self._bot, "runtime", None)
        settings = getattr(runtime, "settings", None)
        channel_id = getattr(settings, "bot_channel_id", 0)
        return channel_id if isinstance(channel_id, int) else 0

    @staticmethod
    def _format_user_label(interaction: discord.Interaction) -> str:
        user = getattr(interaction, "user", None)
        user_id = getattr(user, "id", None)
        display_name = getattr(user, "display_name", None)
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = getattr(user, "name", None)

        if isinstance(display_name, str) and display_name.strip():
            label = f"`{sanitize_audit_text(display_name)}`"
            if isinstance(user_id, int):
                return f"{label} (id={user_id})"
            return label

        if isinstance(user_id, int):
            return f"不明なユーザー (id={user_id})"
        return "不明なユーザー"

    @staticmethod
    def _format_location(interaction: discord.Interaction) -> str:
        channel = getattr(interaction, "channel", None)
        channel_mention = getattr(channel, "mention", None)
        if isinstance(channel_mention, str) and channel_mention:
            return channel_mention

        channel_name = getattr(channel, "name", None)
        if isinstance(channel_name, str) and channel_name.strip():
            return f"`{sanitize_audit_text(channel_name)}`"

        guild = getattr(interaction, "guild", None)
        guild_name = getattr(guild, "name", None)
        if isinstance(guild_name, str) and guild_name.strip():
            return f"`{sanitize_audit_text(guild_name)}`"

        return "DM"

    @staticmethod
    def _truncate_message(content: str) -> str:
        if len(content) <= MAX_AUDIT_MESSAGE_LENGTH:
            return content
        limit = MAX_AUDIT_MESSAGE_LENGTH - len(TRUNCATION_SUFFIX)
        return f"{content[:limit]}{TRUNCATION_SUFFIX}"

    @classmethod
    def build_message(
        cls,
        interaction: discord.Interaction,
        *,
        command_name: str,
        details: Sequence[str] = (),
    ) -> str:
        lines = [
            f"📝 {cls._format_user_label(interaction)} が "
            f"{cls._format_location(interaction)} で "
            f"`{command_name}` を実行しました。"
        ]
        lines.extend(
            f"- {detail.strip()}"
            for detail in details
            if isinstance(detail, str) and detail.strip()
        )
        return cls._truncate_message("\n".join(lines))

    async def log_command(
        self,
        interaction: discord.Interaction,
        *,
        command_name: str,
        details: Sequence[str] = (),
    ) -> None:
        channel_id = self._resolve_channel_id()
        if channel_id <= 0:
            return

        channel = await self._gateway.resolve_messageable_channel(channel_id)
        if channel is None:
            return

        await send_message_safely(
            channel,
            content=self.build_message(
                interaction,
                command_name=command_name,
                details=details,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def log_command_history(
    target: object,
    interaction: discord.Interaction,
    *,
    command_name: str,
    details: Sequence[str] = (),
) -> None:
    audit_logger = getattr(target, "command_audit_logger", None)
    log_method = getattr(audit_logger, "log_command", None)
    if log_method is None:
        return

    await log_method(
        interaction,
        command_name=command_name,
        details=details,
    )
