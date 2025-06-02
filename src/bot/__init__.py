"""
Initialize package and provide bot creation and running functions.
"""
import discord
from discord.ext import commands
from .config import DISCORD_TOKEN, COMMAND_PREFIX
from .cogs_loader import load_cogs


def create_bot() -> commands.Bot:
    """
    Create and configure the Discord bot instance.
    
    Returns:
        Configured Bot instance
    """
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

    @bot.event
    async def on_ready():
        """Event handler for when the bot is ready and connected."""
        print(f"{bot.user} has connected to Discord!")
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")

    return bot


async def run_bot(bot: commands.Bot) -> None:
    """
    Load cogs and start the bot.
    
    Args:
        bot: The bot instance to run
    """
    await load_cogs(bot)
    await bot.start(DISCORD_TOKEN)
