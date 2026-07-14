import datetime
import re
from collections.abc import Sequence

import discord
from discord.ext import commands

from bot.errors import ServiceError
from bot.log import logger
from bot.runtime import get_runtime


def require_guild(interaction: discord.Interaction) -> discord.Guild:
    guild = interaction.guild
    if guild is None:
        raise ServiceError("サーバー内で実行してください。")
    return guild


async def send_safely(
    channel: discord.abc.Messageable,
    content: str | None = None,
    embed: discord.Embed | None = None,
    allowed_mentions: discord.AllowedMentions | None = None,
) -> discord.Message | None:
    try:
        if embed is not None and allowed_mentions is not None:
            return await channel.send(
                content, embed=embed, allowed_mentions=allowed_mentions
            )
        if embed is not None:
            return await channel.send(content, embed=embed)
        if allowed_mentions is not None:
            return await channel.send(content, allowed_mentions=allowed_mentions)
        return await channel.send(content)
    except discord.HTTPException:
        logger.exception("Failed to send message safely")
        return None


async def send_interaction(
    interaction: discord.Interaction,
    content: str,
    ephemeral: bool = True,
) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                content,
                ephemeral=ephemeral,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await interaction.response.send_message(
                content,
                ephemeral=ephemeral,
                allowed_mentions=discord.AllowedMentions.none(),
            )
    except (
        discord.InteractionResponded,
        discord.NotFound,
        discord.HTTPException,
    ):
        logger.exception("Failed to send interaction response")


def format_timestamp(
    value: int | float | datetime.datetime | None, *, style: str = "f"
) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime.datetime):
        unix = int(value.timestamp())
    else:
        unix = int(value)
    return f"<t:{unix}:{style}>"


def format_timestamp_with_relative(value: int | None, *, style: str = "f") -> str:
    if value is None:
        return "-"
    return f"<t:{value}:{style}> (<t:{value}:R>)"


def sanitize_audit_text(value: object) -> str:
    normalized = re.sub(r"\s+", " ", str(value)).strip()
    return normalized.replace("<@", "<@\u200b")


async def log_audit(
    bot: commands.Bot,
    interaction: discord.Interaction,
    *,
    command_name: str,
    details: Sequence[str] = (),
) -> None:
    try:
        runtime = get_runtime(bot)
    except RuntimeError:
        return
    channel_id = runtime.settings.bot_channel_id
    if channel_id is None:
        return

    channel = await resolve_messageable(bot, channel_id)
    if channel is None:
        return

    channel_name = getattr(interaction.channel, "name", "unknown")
    user_name = getattr(interaction.user, "display_name", str(interaction.user))
    lines = [
        f"📝 `{sanitize_audit_text(user_name)}` (id={interaction.user.id}) "
        f"が #{sanitize_audit_text(channel_name)} で "
        f"`/{sanitize_audit_text(command_name)}` を実行しました。"
    ]
    lines.extend(f"- {sanitize_audit_text(item)}" for item in details)
    content = "\n".join(lines)
    if len(content) > 1900:
        content = content[:1897] + "..."
    await send_safely(channel, content, allowed_mentions=discord.AllowedMentions.none())


async def resolve_messageable(
    bot: commands.Bot,
    channel_id: int | None,
) -> discord.abc.Messageable | None:
    if channel_id is None:
        return None
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.NotFound, discord.Forbidden, discord.HTTPException:
            return None
    if isinstance(channel, discord.abc.Messageable):
        return channel
    return None


async def fetch_member(
    guild: discord.Guild,
    user_id: int,
) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound, discord.Forbidden, discord.HTTPException:
        return None
