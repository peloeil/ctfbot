import logging

import discord

logger = logging.getLogger("ctfbot")


def configure_logging(level: str) -> None:
    """Configure root logger once at startup."""
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return

    logging.basicConfig(
        level=level,
        format="%(asctime)s:%(levelname)s:%(name)s: %(message)s",
    )


async def send_message_safely(
    channel: discord.abc.Messageable,
    content: str | None = None,
    embed: discord.Embed | None = None,
) -> discord.Message | None:
    """
    Safely send a message to a channel with error handling.

    Args:
        channel: The channel to send the message to
        content: The message content (optional)
        embed: The embed to send (optional)

    Returns:
        The sent message or None if sending failed
    """
    if content is None and embed is None:
        raise ValueError("Either content or embed must be provided")

    try:
        if content is not None and embed is not None:
            return await channel.send(content=content, embed=embed)
        if content is not None:
            return await channel.send(content=content)
        assert embed is not None
        return await channel.send(embed=embed)
    except discord.HTTPException:
        logger.exception("Failed to send message")
        return None


async def send_interaction_message(
    interaction: discord.Interaction, content: str, ephemeral: bool = True
) -> None:
    """Send interaction response safely, handling already-responded state."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral)
    except discord.HTTPException:
        logger.exception("Failed to send interaction response")


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
