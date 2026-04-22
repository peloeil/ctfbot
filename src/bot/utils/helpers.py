import datetime
from typing import Any, cast

import discord

from ..log import logger


async def send_message_safely(
    channel: discord.abc.Messageable,
    content: str | None = None,
    embed: discord.Embed | None = None,
    allowed_mentions: discord.AllowedMentions | None = None,
) -> discord.Message | None:
    """
    Safely send a message to a channel with error handling.

    Args:
        channel: The channel to send the message to
        content: The message content (optional)
        embed: The embed to send (optional)
        allowed_mentions: Optional mention policy override

    Returns:
        The sent message or None if sending failed
    """
    if content is None and embed is None:
        raise ValueError("Either content or embed must be provided")

    sender = cast(Any, channel)

    try:
        if content is not None and embed is not None:
            return await sender.send(
                content,
                embed=embed,
                allowed_mentions=allowed_mentions,
            )
        if content is not None:
            return await sender.send(content, allowed_mentions=allowed_mentions)
        assert embed is not None
        return await sender.send(
            None,
            embed=embed,
            allowed_mentions=allowed_mentions,
        )
    except discord.HTTPException:
        logger.exception("Failed to send message")
        return None


async def send_interaction_message(
    interaction: discord.Interaction, content: str, ephemeral: bool = True
) -> None:
    """Send interaction response safely, handling already-responded state."""
    if interaction.is_expired():
        logger.warning(
            "Skipped interaction response because interaction expired: id=%s",
            interaction.id,
        )
        return

    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral)
    except discord.NotFound:
        logger.warning(
            "Failed to send interaction response because interaction expired: id=%s",
            interaction.id,
        )
    except discord.HTTPException:
        logger.exception("Failed to send interaction response")


def format_discord_timestamp(
    value: int | float | datetime.datetime | None,
    *,
    style: str = "f",
) -> str:
    """Format a value as a Discord timestamp token."""
    if value is None:
        return "-"

    if isinstance(value, datetime.datetime):
        normalized = value
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=datetime.UTC)
        unix = int(normalized.astimezone(datetime.UTC).timestamp())
    else:
        unix = int(value)

    return f"<t:{unix}:{style}>"


def format_code_block(content: str, language: str = "") -> str:
    """
    Format content as a Discord code block.

    Args:
        content: The content to format
        language: Optional language for syntax highlighting

    Returns:
        Formatted code block string
    """
    return f"```{language}\n{content}\n```"


def chunk_message(message: str, chunk_size: int = 1900) -> list[str]:
    """
    Split a message into chunks that fit within Discord's message size limits.

    Args:
        message: The message to split
        chunk_size: Maximum size of each chunk

    Returns:
        List of message chunks
    """
    return [message[i : i + chunk_size] for i in range(0, len(message), chunk_size)]
