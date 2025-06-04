"""
Tasks loop cog for the CTF Discord bot.
Contains scheduled tasks that run at specific times.
"""

from datetime import time

import discord
from discord.ext import commands, tasks

from ...config import BOT_CHANNEL_ID, JST
from ...utils.helpers import logger, send_message_safely


class TasksLoopExample(commands.Cog):
    """Cog for scheduled tasks that run at specific times."""

    def __init__(self, bot: commands.Bot) -> None:
        """
        Initialize the TasksLoop cog.

        Args:
            bot: The bot instance
        """
        self.bot = bot
        self.goodmorning.start()

    @tasks.loop(time=[time(hour=4, minute=47, tzinfo=JST)])
    async def goodmorning(self) -> None:
        """Scheduled task to send a good morning message at 4:47 AM JST."""
        channel = self.bot.get_channel(BOT_CHANNEL_ID)
        if channel is None:
            logger.error("Channel not found. Check the BOT_CHANNEL_ID configuration.")
            return
        if not isinstance(channel, discord.abc.Messageable):
            logger.error("Channel is not messageable. Check the channel type.")
            return
        await send_message_safely(channel, "おはよう! 朝4時に何してるんだい?")

    def cog_unload(self) -> None:
        """Clean up when the cog is unloaded."""
        self.goodmorning.cancel()


async def setup(bot: commands.Bot) -> None:
    """
    Add the TasksLoop cog to the bot.

    Args:
        bot: The bot instance
    """
    await bot.add_cog(TasksLoopExample(bot))
