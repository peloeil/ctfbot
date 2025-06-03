"""
Utility functions for the CTF Discord bot.
Contains common helper functions used across the bot.
"""

import logging
from typing import Any

import discord

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ctfbot")


async def send_message_safely(
    channel: discord.abc.Messageable, content: str
) -> discord.Message | None:
    """
    Safely send a message to a channel with error handling.

    Args:
        channel: The channel to send the message to
        content: The message content

    Returns:
        The sent message or None if sending failed
    """
    try:
        return await channel.send(content)
    except discord.DiscordException as e:
        logger.error(f"Failed to send message: {e}")
        return None


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


def handle_error(error: Exception, context: Any = None) -> str:
    """
    Handle an exception and return an appropriate error message.
    Also logs the error.

    Args:
        error: The exception to handle
        context: Optional context information

    Returns:
        Error message for the user
    """
    error_type = type(error).__name__
    error_message = str(error)

    logger.error(f"Error ({error_type}): {error_message}", exc_info=True)
    if context:
        logger.error(f"Context: {context}")

    return f"An error occurred: {error_message}"
