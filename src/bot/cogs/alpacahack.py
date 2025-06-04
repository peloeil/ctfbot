"""
AlpacaHack cog for the CTF Discord bot.
Handles commands and tasks related to AlpacaHack CTF platform.
"""

import asyncio
from datetime import time

from discord.ext import commands, tasks

from ..config import BOT_CHANNEL_ID, JST
from ..db.database import (
    create_alpacahack_user_table_if_not_exists,
    delete_alpacahack_user,
    get_all_alpacahack_users,
    insert_alpacahack_user,
)
from ..services.alpacahack_service import get_alpacahack_info
from ..utils.helpers import format_code_block, logger, send_message_safely


class Alpacahack(commands.Cog):
    """Cog for AlpacaHack CTF platform integration."""

    def __init__(self, bot):
        """
        Initialize the Alpacahack cog.

        Args:
            bot: The bot instance
        """
        # Initialize database if needed
        create_alpacahack_user_table_if_not_exists()

        self.bot = bot
        self.alpacahack_solves.start()

    @tasks.loop(time=[time(hour=23, minute=0, tzinfo=JST)])
    async def alpacahack_solves(self):
        """Task to fetch and post AlpacaHack solve information at 11:00 PM JST."""
        channel = self.bot.get_channel(BOT_CHANNEL_ID)
        if channel is not None:
            try:
                users = get_all_alpacahack_users()
                for user in users:
                    await send_message_safely(channel, f"## {user[0]}")
                    for info in get_alpacahack_info(user[0]):
                        await send_message_safely(channel, format_code_block(info))
                    await asyncio.sleep(1)  # Rate limiting
            except Exception as e:
                logger.error(f"Failed to fetch AlpacaHack data: {e}")
        else:
            logger.error("Channel not found. Check the channel ID.")

    @commands.command()
    async def add_alpaca(self, ctx, name: str):
        """
        Add a user to the AlpacaHack tracking database.

        Args:
            ctx: Command context
            name: Username to add
        """
        result = insert_alpacahack_user(name)
        await send_message_safely(ctx.channel, content=result)

    @commands.command()
    async def del_alpaca(self, ctx, name: str):
        """
        Remove a user from the AlpacaHack tracking database.

        Args:
            ctx: Command context
            name: Username to remove
        """
        result = delete_alpacahack_user(name)
        await send_message_safely(ctx.channel, content=result)

    @commands.command()
    async def show_alpaca(self, ctx):
        """
        Show all users in the AlpacaHack tracking database.

        Args:
            ctx: Command context
        """
        users = get_all_alpacahack_users()
        if not users:
            await send_message_safely(ctx.channel, content="誰も登録されていません")
        else:
            user_list = "\n".join(user[0] for user in users)
            await send_message_safely(ctx.channel, content=format_code_block(user_list))

    @commands.command()
    async def show_alpaca_score(self, ctx):
        """
        Show scores for all tracked AlpacaHack users.

        Args:
            ctx: Command context
        """
        try:
            users = get_all_alpacahack_users()
            for user in users:
                await send_message_safely(ctx.channel, content=f"## {user[0]}")
                for info in get_alpacahack_info(user[0]):
                    await send_message_safely(
                        ctx.channel, content=format_code_block(info)
                    )
                await asyncio.sleep(1)  # Rate limiting
        except Exception as e:
            await send_message_safely(
                ctx.channel, content=f"Failed to fetch AlpacaHack data: {e}"
            )

    def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.alpacahack_solves.cancel()


async def setup(bot):
    """
    Add the Alpacahack cog to the bot.

    Args:
        bot: The bot instance
    """
    await bot.add_cog(Alpacahack(bot))
