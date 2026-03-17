from discord.ext import commands

from .log import logger

DEFAULT_EXTENSIONS = (
    "bot.cogs.manage_cogs",
    "bot.cogs.help_command",
    "bot.cogs.message_tools",
    "bot.cogs.perms_debug",
    "bot.cogs.times_channels",
    "bot.features.alpacahack.cog",
    "bot.features.ctf_team.cog",
    "bot.features.ctftime.cog",
)


async def load_cogs(bot: commands.Bot) -> None:
    """Load required production cogs for the bot (fail-fast)."""
    for cog in DEFAULT_EXTENSIONS:
        try:
            await bot.load_extension(cog)
            logger.info("Loaded extension: %s", cog)
        except Exception as exc:
            logger.exception("Failed to load extension: %s", cog)
            raise RuntimeError(f"Failed to load required extension: {cog}") from exc
