from __future__ import annotations

import asyncio
import datetime

import discord
from discord.ext import commands, tasks

from ...cogs._runtime import get_runtime
from ...discord_gateway import DiscordGateway
from ...utils.helpers import format_code_block, logger, send_message_safely
from .usecase import WeeklySolveSummary

WEEKLY_NOTIFICATION_WEEKDAY = 6  # 0=Mon ... 6=Sun


class Alpacahack(commands.Cog):
    """Commands and scheduled notifications for AlpacaHack users."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = get_runtime(bot)
        self.settings = self.runtime.settings
        self.gateway = DiscordGateway(bot, logger)
        self.usecase = self.runtime.alpacahack_usecase
        self.alpacahack_solves.change_interval(time=self.settings.alpacahack_solve_time)
        self.alpacahack_solves.start()

    async def cog_unload(self) -> None:
        self.alpacahack_solves.cancel()

    async def _resolve_target_channel(self) -> discord.abc.Messageable | None:
        return await self.gateway.resolve_messageable_channel(
            self.settings.bot_channel_id
        )

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

    def _build_weekly_summary_embed(self, summary: WeeklySolveSummary) -> discord.Embed:
        total_solves = sum(len(items) for items in summary.weekly_solves.values())
        solved_users = len(summary.weekly_solves)

        embed = discord.Embed(
            title="🦙 AlpacaHack 今週の solve",
            description=(
                f"{summary.week_start:%Y-%m-%d} 〜 {summary.week_end:%Y-%m-%d}\n"
                f"{solved_users}/{summary.total_users} 人, {total_solves} solves"
            ),
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(self.settings.tzinfo),
        )

        if not summary.weekly_solves:
            embed.add_field(
                name="進捗",
                value="今週の solve はまだありません。",
                inline=False,
            )
            return embed

        sorted_rows = sorted(
            summary.weekly_solves.items(),
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

    async def _send_weekly_summary_embed(
        self,
        target_channel: discord.abc.Messageable,
        period_end: datetime.date,
        *,
        notify_if_no_users: bool,
    ) -> None:
        summary = await asyncio.to_thread(
            self.usecase.collect_weekly_summary, period_end
        )
        if summary.total_users == 0:
            if notify_if_no_users:
                await send_message_safely(
                    target_channel, content="誰も登録されていません"
                )
            return

        embed = self._build_weekly_summary_embed(summary)
        await send_message_safely(target_channel, embed=embed)

    @tasks.loop()
    async def alpacahack_solves(self) -> None:
        today = datetime.datetime.now(self.settings.tzinfo).date()
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
        result = await asyncio.to_thread(self.usecase.add_user, name)
        await send_message_safely(ctx.channel, content=result)

    @commands.command()
    async def del_alpaca(self, ctx: commands.Context, name: str) -> None:
        result = await asyncio.to_thread(self.usecase.delete_user, name)
        await send_message_safely(ctx.channel, content=result)

    @commands.command()
    async def show_alpaca(self, ctx: commands.Context) -> None:
        usernames = await asyncio.to_thread(self.usecase.list_usernames)
        if not usernames:
            await send_message_safely(ctx.channel, content="誰も登録されていません")
            return

        user_list = "\n".join(usernames)
        await send_message_safely(ctx.channel, content=format_code_block(user_list))

    @commands.command()
    async def show_alpaca_score(self, ctx: commands.Context) -> None:
        today = datetime.datetime.now(self.settings.tzinfo).date()
        await self._send_weekly_summary_embed(
            target_channel=ctx.channel,
            period_end=today,
            notify_if_no_users=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Alpacahack(bot))
