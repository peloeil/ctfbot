"""
Cogs loader module for the CTF Discord bot.
Handles loading and management of bot cogs.
"""

from discord.ext import commands


async def load_cogs(bot: commands.Bot) -> None:
    """
    Load all cogs for the bot.

    Args:
        bot: The bot instance to load cogs for
    """
    extensions = [
        "bot.cogs.examples.basic_commands",
        "bot.cogs.manage_cogs",
        "bot.cogs.slash_commands",
        "bot.cogs.alpacahack",
        "bot.cogs.ctftime_notifications",
        "bot.cogs.ctf_management",
    ]

    for cog in extensions:
        try:
            await bot.load_extension(cog)
            print(f"Loaded extension: {cog}")
        except Exception as e:
            print(f"Failed to load extension {cog}: {e}")
