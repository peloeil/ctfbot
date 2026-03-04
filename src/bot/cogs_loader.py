from discord.ext import commands

from .utils.helpers import logger

DEFAULT_EXTENSIONS = (
    "bot.cogs.manage_cogs",
    "bot.cogs.slash_commands",
    "bot.cogs.alpacahack",
    "bot.cogs.ctftime_notifications",
)


async def load_cogs(bot: commands.Bot) -> None:
    """Load production cogs for the bot."""
    for cog in DEFAULT_EXTENSIONS:
        try:
            await bot.load_extension(cog)
            logger.info("Loaded extension: %s", cog)
        except Exception:
            logger.exception("Failed to load extension: %s", cog)
