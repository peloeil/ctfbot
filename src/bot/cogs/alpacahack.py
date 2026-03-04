import asyncio
import datetime

import discord
from discord.ext import commands, tasks

from ..config import settings
from ..db.database import (
    create_alpacahack_user_table_if_not_exists,
    delete_alpacahack_user,
    get_all_alpacahack_users,
    insert_alpacahack_user,
)
from ..services.alpacahack_service import get_alpacahack_info
from ..utils.helpers import format_code_block, logger, send_message_safely


def _parse_daily_time(raw_value: str) -> datetime.time:
    try:
        hour_str, minute_str = raw_value.split(":", maxsplit=1)
        hour = int(hour_str)
        minute = int(minute_str)
    except ValueError:
        return datetime.time(hour=23, minute=0, tzinfo=settings.tzinfo)

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return datetime.time(hour=23, minute=0, tzinfo=settings.tzinfo)
    return datetime.time(hour=hour, minute=minute, tzinfo=settings.tzinfo)


ALPACAHACK_SOLVE_TIME = _parse_daily_time(settings.alpacahack_solve_time)


class Alpacahack(commands.Cog):
    """Commands and scheduled notifications for AlpacaHack users."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        create_alpacahack_user_table_if_not_exists()
        self.alpacahack_solves.start()

    async def cog_unload(self) -> None:
        self.alpacahack_solves.cancel()

    async def _resolve_target_channel(self) -> discord.abc.Messageable | None:
        channel_id = settings.bot_channel_id
        if channel_id <= 0:
            return None

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.exception("Failed to resolve channel: %s", channel_id)
                return None

        if not isinstance(channel, discord.abc.Messageable):
            logger.warning("Configured channel %s is not messageable", channel_id)
            return None
        return channel

    async def _render_user_info_messages(self, username: str) -> list[str]:
        sections = await asyncio.to_thread(lambda: list(get_alpacahack_info(username)))
        if not sections:
            return [format_code_block("No data found")]
        return [format_code_block(section) for section in sections]

    @tasks.loop(time=[ALPACAHACK_SOLVE_TIME])
    async def alpacahack_solves(self) -> None:
        """Post all tracked AlpacaHack user summaries daily."""
        channel = await self._resolve_target_channel()
        if channel is None:
            return

        users = await asyncio.to_thread(get_all_alpacahack_users)
        if not users:
            return

        for user_row in users:
            username = str(user_row[0])
            await send_message_safely(channel, content=f"## {username}")
            for message in await self._render_user_info_messages(username):
                await send_message_safely(channel, content=message)
            await asyncio.sleep(0.5)

    @alpacahack_solves.before_loop
    async def before_alpacahack_solves(self) -> None:
        await self.bot.wait_until_ready()

    @commands.command()
    async def add_alpaca(self, ctx: commands.Context, name: str) -> None:
        result = await asyncio.to_thread(insert_alpacahack_user, name)
        await send_message_safely(ctx.channel, content=result)

    @commands.command()
    async def del_alpaca(self, ctx: commands.Context, name: str) -> None:
        result = await asyncio.to_thread(delete_alpacahack_user, name)
        await send_message_safely(ctx.channel, content=result)

    @commands.command()
    async def show_alpaca(self, ctx: commands.Context) -> None:
        users = await asyncio.to_thread(get_all_alpacahack_users)
        if not users:
            await send_message_safely(ctx.channel, content="誰も登録されていません")
            return

        user_list = "\n".join(str(user[0]) for user in users)
        await send_message_safely(ctx.channel, content=format_code_block(user_list))

    @commands.command()
    async def show_alpaca_score(self, ctx: commands.Context) -> None:
        users = await asyncio.to_thread(get_all_alpacahack_users)
        if not users:
            await send_message_safely(ctx.channel, content="誰も登録されていません")
            return

        for user_row in users:
            username = str(user_row[0])
            await send_message_safely(ctx.channel, content=f"## {username}")
            for message in await self._render_user_info_messages(username):
                await send_message_safely(ctx.channel, content=message)
            await asyncio.sleep(0.5)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Alpacahack(bot))
