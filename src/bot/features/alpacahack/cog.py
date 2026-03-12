from __future__ import annotations

import asyncio
import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ...cogs._runtime import get_runtime
from ...utils.helpers import (
    logger,
    send_interaction_message,
    send_message_safely,
)
from .models import SolvedChallenge, UserMutationResult, UserMutationStatus
from .usecase import WeeklySolveSummary

WEEKLY_NOTIFICATION_WEEKDAY = 6  # 0=Mon ... 6=Sun
CTF_CATEGORY_NAME = "ctf"
ALPACAHACK_CHANNEL_NAME = "alpacahack"


class Alpacahack(
    commands.GroupCog,
    group_name="alpaca",
    group_description="AlpacaHack関連コマンドです。",
):
    """Commands and scheduled notifications for AlpacaHack users."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = get_runtime(bot)
        self.settings = self.runtime.settings
        self.usecase = self.runtime.alpacahack_usecase
        self.alpacahack_solves.change_interval(time=self.settings.alpacahack_solve_time)
        self.alpacahack_solves.start()

    async def cog_unload(self) -> None:
        self.alpacahack_solves.cancel()

    @staticmethod
    def _normalize_name(name: str) -> str:
        return name.strip().lower()

    @classmethod
    def _find_alpacahack_channel(
        cls, guild: discord.Guild
    ) -> discord.TextChannel | None:
        for category in guild.categories:
            if cls._normalize_name(category.name) != CTF_CATEGORY_NAME:
                continue
            for channel in category.text_channels:
                if cls._normalize_name(channel.name) == ALPACAHACK_CHANNEL_NAME:
                    return channel
        return None

    async def _resolve_target_channel(self) -> discord.abc.Messageable | None:
        for guild in self.bot.guilds:
            channel = self._find_alpacahack_channel(guild)
            if channel is not None:
                return channel
        logger.warning(
            "Could not find #%s under %s category in joined guilds",
            ALPACAHACK_CHANNEL_NAME,
            CTF_CATEGORY_NAME,
        )
        return None

    @staticmethod
    def _format_lines(
        entries: list[str],
        *,
        empty_message: str,
        max_items: int,
        max_length: int = 1024,
    ) -> str:
        if not entries:
            return empty_message

        lines: list[str] = []
        for entry in entries[:max_items]:
            if len("\n".join([*lines, entry])) > max_length:
                if not lines:
                    return (
                        f"{entry[: max_length - 3]}..."
                        if len(entry) > max_length
                        else entry
                    )
                break
            lines.append(entry)

        omitted = len(entries) - len(lines)
        if omitted > 0:
            overflow = f"... 他 {omitted} 件"
            if len("\n".join([*lines, overflow])) <= max_length:
                lines.append(overflow)

        return "\n".join(lines)

    @staticmethod
    def _format_solve_entry(solve: SolvedChallenge) -> str:
        name = discord.utils.escape_markdown(solve.name, as_needed=True)
        if solve.url:
            return f"- [{name}]({solve.url})"
        return f"- {name}"

    @classmethod
    def _format_solve_list(
        cls, solves: list[SolvedChallenge], max_items: int = 12
    ) -> str:
        return cls._format_lines(
            [cls._format_solve_entry(solve) for solve in solves],
            empty_message="今週の solve はありません。",
            max_items=max_items,
        )

    @staticmethod
    def _format_failed_users(users: list[str], max_items: int = 20) -> str:
        return Alpacahack._format_lines(
            [f"- {name}" for name in users],
            empty_message="-",
            max_items=max_items,
        )

    @staticmethod
    def _format_username_entry(username: str) -> str:
        escaped = discord.utils.escape_markdown(username, as_needed=True)
        return f"- {escaped}"

    @classmethod
    def _format_username_list(cls, usernames: list[str]) -> str:
        header = "登録済みAlpacaHackユーザー"
        available_length = 1900 - len(header) - 1
        body = cls._format_lines(
            [cls._format_username_entry(username) for username in usernames],
            empty_message="誰も登録されていません。",
            max_items=len(usernames),
            max_length=available_length,
        )
        return f"{header}\n{body}"

    @staticmethod
    def _to_user_message(result: UserMutationResult) -> str:
        if result.status == UserMutationStatus.INVALID_NAME:
            return "ユーザー名が空です。"
        if result.status == UserMutationStatus.CREATED:
            return f"`{result.normalized_name}` を登録しました。"
        if result.status == UserMutationStatus.ALREADY_EXISTS:
            return f"`{result.normalized_name}` は既に登録されています。"
        if result.status == UserMutationStatus.DELETED:
            return f"`{result.normalized_name}` の登録を削除しました。"
        if result.status == UserMutationStatus.NOT_FOUND:
            return f"`{result.normalized_name}` は登録されていません。"
        return "不明な結果です。"

    def _build_weekly_summary_embed(self, summary: WeeklySolveSummary) -> discord.Embed:
        total_solves = sum(len(items) for items in summary.weekly_solves.values())
        solved_users = len(summary.weekly_solves)
        failed_users = len(summary.failed_users)

        embed = discord.Embed(
            title="🦙 AlpacaHack 今週の solve",
            description=(
                f"{summary.week_start:%Y-%m-%d} 〜 {summary.week_end:%Y-%m-%d}\n"
                f"{solved_users}/{summary.total_users} 人, {total_solves} solves, "
                f"取得失敗 {failed_users} 人"
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
            if not summary.failed_users:
                return embed
            embed.add_field(
                name="取得失敗ユーザー",
                value=self._format_failed_users(summary.failed_users),
                inline=False,
            )
            return embed

        sorted_rows = sorted(
            summary.weekly_solves.items(),
            key=lambda row: len(row[1]),
            reverse=True,
        )

        max_user_fields = 24 if summary.failed_users else 25
        for username, solves in sorted_rows[:max_user_fields]:
            embed.add_field(
                name=username,
                value=self._format_solve_list(solves),
                inline=False,
            )

        if summary.failed_users:
            embed.add_field(
                name="取得失敗ユーザー",
                value=self._format_failed_users(summary.failed_users),
                inline=False,
            )

        if len(sorted_rows) > max_user_fields:
            embed.set_footer(
                text=(
                    f"Discord上限のため他 {len(sorted_rows) - max_user_fields} 人を省略"
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
        if summary.total_users != 0:
            embed = self._build_weekly_summary_embed(summary)
            await send_message_safely(target_channel, embed=embed)
            return

        if not notify_if_no_users:
            return
        await send_message_safely(target_channel, content="誰も登録されていません。")

    async def _send_weekly_summary_interaction(
        self,
        interaction: discord.Interaction,
        period_end: datetime.date,
        *,
        notify_if_no_users: bool,
    ) -> None:
        summary = await asyncio.to_thread(
            self.usecase.collect_weekly_summary, period_end
        )
        if summary.total_users == 0:
            if not notify_if_no_users:
                return
            await send_interaction_message(
                interaction,
                "誰も登録されていません。",
                ephemeral=True,
            )
            return

        embed = self._build_weekly_summary_embed(summary)
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=False)
            return
        await interaction.response.send_message(embed=embed, ephemeral=False)

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

    @app_commands.command(
        name="add",
        description="AlpacaHackユーザーを登録します。",
    )
    @app_commands.describe(name="登録するユーザー名")
    async def alpaca_add(self, interaction: discord.Interaction, name: str) -> None:
        result = await asyncio.to_thread(self.usecase.add_user, name)
        await send_interaction_message(
            interaction,
            self._to_user_message(result),
            ephemeral=True,
        )

    @app_commands.command(
        name="del",
        description="AlpacaHackユーザーの登録を削除します。",
    )
    @app_commands.describe(name="削除するユーザー名")
    async def alpaca_del(self, interaction: discord.Interaction, name: str) -> None:
        result = await asyncio.to_thread(self.usecase.delete_user, name)
        await send_interaction_message(
            interaction,
            self._to_user_message(result),
            ephemeral=True,
        )

    @app_commands.command(
        name="list",
        description="登録済みのAlpacaHackユーザー一覧を表示します。",
    )
    async def alpaca_list(self, interaction: discord.Interaction) -> None:
        usernames = await asyncio.to_thread(self.usecase.list_usernames)
        if not usernames:
            await send_interaction_message(
                interaction,
                "誰も登録されていません。",
                ephemeral=True,
            )
            return

        await send_interaction_message(
            interaction,
            self._format_username_list(usernames),
            ephemeral=True,
        )

    @app_commands.command(
        name="solve",
        description="AlpacaHackの今週のsolve状況を表示します。",
    )
    async def alpaca_solve(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer(thinking=True)
        today = datetime.datetime.now(self.settings.tzinfo).date()
        await self._send_weekly_summary_interaction(
            interaction=interaction,
            period_end=today,
            notify_if_no_users=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Alpacahack(bot))
