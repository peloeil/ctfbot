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
from ..services.alpacahack_service import (
    get_week_range,
    get_weekly_solve_challenges,
)
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
WEEKLY_NOTIFICATION_WEEKDAY = 6  # 0=Mon ... 6=Sun


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

    @staticmethod
    def _format_solve_list(solves: list[str], max_items: int = 12) -> str:
        if not solves:
            return "今週の solve はありません。"

        lines = [f"- {name}" for name in solves[:max_items]]
        if len(solves) > max_items:
            lines.append(f"... and {len(solves) - max_items} more")

        joined = "\n".join(lines)
        if len(joined) > 1024:
            return f"{joined[:1020]}..."
        return joined

    def _build_weekly_summary_embed(
        self,
        weekly_solves: dict[str, list[str]],
        week_start: datetime.date,
        week_end: datetime.date,
        total_users: int,
    ) -> discord.Embed:
        total_solves = sum(len(items) for items in weekly_solves.values())
        solved_users = len(weekly_solves)

        embed = discord.Embed(
            title="🦙 AlpacaHack 今週の solve",
            description=(
                f"{week_start:%Y-%m-%d} 〜 {week_end:%Y-%m-%d}\n"
                f"{solved_users}/{total_users} 人, {total_solves} solves"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(settings.tzinfo),
        )

        if not weekly_solves:
            embed.add_field(
                name="進捗",
                value="今週の solve はまだありません。",
                inline=False,
            )
            return embed

        sorted_rows = sorted(
            weekly_solves.items(),
            key=lambda row: len(row[1]),
            reverse=True,
        )

        for username, solves in sorted_rows[:25]:
            embed.add_field(
                name=username,
                value=self._format_solve_list(solves),
                inline=False,
            )

        if len(sorted_rows) > 25:
            embed.set_footer(
                text=(
                    f"+ {len(sorted_rows) - 25} users are omitted due to Discord limits"
                )
            )

        return embed

    async def _collect_weekly_solves(
        self, users: list[tuple[str]], today: datetime.date
    ) -> dict[str, list[str]]:
        weekly_solves: dict[str, list[str]] = {}

        for user_row in users:
            username = str(user_row[0])
            solves = await asyncio.to_thread(
                get_weekly_solve_challenges, username, today
            )
            if solves:
                weekly_solves[username] = solves
            await asyncio.sleep(0.2)

        return weekly_solves

    async def _send_weekly_summary_embed(
        self,
        target_channel: discord.abc.Messageable,
        period_end: datetime.date,
        *,
        notify_if_no_users: bool,
    ) -> None:
        users = await asyncio.to_thread(get_all_alpacahack_users)
        if not users:
            if notify_if_no_users:
                await send_message_safely(
                    target_channel, content="誰も登録されていません"
                )
            return

        today = datetime.datetime.now(settings.tzinfo).date()
        week_start, week_end = get_week_range(today)
        weekly_solves = await self._collect_weekly_solves(users, today)

        embed = self._build_weekly_summary_embed(
            weekly_solves=weekly_solves,
            week_start=week_start,
            week_end=period_end if period_end >= week_start else week_end,
            total_users=len(users),
        )
        await send_message_safely(target_channel, embed=embed)

    @tasks.loop(time=[ALPACAHACK_SOLVE_TIME])
    async def alpacahack_solves(self) -> None:
        """Post weekly AlpacaHack solve summary for tracked users."""
        today = datetime.datetime.now(settings.tzinfo).date()
        if today.weekday() != WEEKLY_NOTIFICATION_WEEKDAY:
            return

        channel = await self._resolve_target_channel()
        if channel is None:
            return

        await self._send_weekly_summary_embed(
            target_channel=channel,
            period_end=today,
            notify_if_no_users=False,
        )

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
        today = datetime.datetime.now(settings.tzinfo).date()
        await self._send_weekly_summary_embed(
            target_channel=ctx.channel,
            period_end=today,
            notify_if_no_users=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Alpacahack(bot))
