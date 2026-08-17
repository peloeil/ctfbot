import asyncio
import datetime
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.errors import ConflictError, ExternalAPIError
from bot.features.alpacahack.service import (
    AlpacaHackClient,
    DailyChallenge,
    WeeklySolveSummary,
    collect_weekly_summary,
)
from bot.helpers import (
    is_markdown_link_safe,
    log_audit,
    resolve_messageable,
    send_interaction,
    send_safely,
)
from bot.log import logger
from bot.runtime import get_runtime

MAX_EMBED_FIELDS = 25
ALPACAHACK_EMBED_COLOR = 0xFD8028
_MAX_USERNAME_LENGTH = 32
_USERNAME_PATTERN = re.compile(r"[0-9A-Za-z_-]+")
_MAX_USERS = 50
_EMBED_TOTAL_LIMIT = 6000
_FINAL_FIELD_RESERVE = 1100  # Room for the final summary field (name + value)
_DAILY_DESCRIPTION_LIMIT = 3500


def _build_summary_embed(summary: WeeklySolveSummary) -> discord.Embed:
    solved_users = sum(1 for solves in summary.weekly_solves.values() if solves)
    total_solves = sum(len(solves) for solves in summary.weekly_solves.values())
    description = (
        f"{summary.week_start} 〜 {summary.week_end}\n"
        f"{solved_users}人/{summary.total_users}人, {total_solves} solves"
    )
    if summary.failed_users:
        description += f"\n取得失敗 {len(summary.failed_users)}人"
    embed = discord.Embed(
        title="🦙 AlpacaHack 今週の solve",
        description=description,
        color=ALPACAHACK_EMBED_COLOR,
    )
    total = len(embed.title or "") + len(description)
    visible_items = list(summary.weekly_solves.items())[: MAX_EMBED_FIELDS - 1]
    shown = 0
    for username, solves in visible_items:
        value_lines: list[str] = []
        for record in solves[:12]:
            if (
                record.challenge_url
                and is_markdown_link_safe(record.challenge_url)
                and is_markdown_link_safe(record.challenge_name)
            ):
                value_lines.append(
                    f"- [{record.challenge_name}]({record.challenge_url})"
                )
            else:
                value_lines.append(f"- {record.challenge_name}")
        if len(solves) > 12:
            value_lines.append(f"... 他 {len(solves) - 12} 件")
        value = "\n".join(value_lines) or "-"
        if len(value) > 1024:
            value = value[:1021] + "..."
        name = f"{username} ({len(solves)} solves)"
        if total + len(name) + len(value) > _EMBED_TOTAL_LIMIT - _FINAL_FIELD_RESERVE:
            break
        embed.add_field(
            name=name,
            value=value,
            inline=False,
        )
        total += len(name) + len(value)
        shown += 1
    omitted_users = len(summary.weekly_solves) - shown
    if omitted_users or summary.failed_users:
        extra_lines: list[str] = []
        if omitted_users:
            extra_lines.append(f"他 {omitted_users} 人は省略しました。")
        if summary.failed_users:
            failed = ", ".join(summary.failed_users)
            extra_lines.append(f"取得失敗: {failed}")
        embed.add_field(
            name="その他 / 取得失敗" if summary.failed_users else "その他",
            value="\n".join(extra_lines)[:1024],
            inline=False,
        )
    return embed


def _build_daily_embed(challenge: DailyChallenge) -> discord.Embed:
    description = challenge.description
    if len(description) > _DAILY_DESCRIPTION_LIMIT:
        description = description[: _DAILY_DESCRIPTION_LIMIT - 3] + "..."
    embed = discord.Embed(
        title=f"🦙 {challenge.title}"[:256],
        url=challenge.url,
        description=description or "問題ページを確認してください。",
        color=ALPACAHACK_EMBED_COLOR,
    )
    categories = " / ".join(challenge.categories) or "-"
    embed.add_field(
        name="カテゴリ / 難易度",
        value=f"{categories} / {challenge.difficulty}"[:256],
        inline=True,
    )
    embed.add_field(name="作問者", value=challenge.author[:256], inline=True)
    if challenge.attachment_urls:
        lines = []
        for url in challenge.attachment_urls:
            name = unquote(PurePosixPath(urlparse(url).path).name) or "添付ファイル"
            lines.append(
                f"- [{name}]({url})"
                if is_markdown_link_safe(name) and is_markdown_link_safe(url)
                else url
            )
        value = "\n".join(lines)
        embed.add_field(
            name="添付ファイル",
            value=value if len(value) <= 1024 else value[:1021] + "...",
            inline=False,
        )
    return embed


class Alpacahack(commands.GroupCog, group_name="alpaca"):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        runtime = get_runtime(bot)
        self.bot = bot
        self.settings = runtime.settings
        self.db = runtime.db
        self.client = AlpacaHackClient(timezone=self.settings.tzinfo)
        self.weekly_solve_report.change_interval(
            time=self.settings.alpacahack_solve_time
        )
        self.daily_challenge_report.change_interval(
            time=self.settings.alpacahack_daily_time
        )
        self.weekly_solve_report.start()
        self.daily_challenge_report.start()

    async def cog_unload(self) -> None:
        self.weekly_solve_report.cancel()
        self.daily_challenge_report.cancel()

    @tasks.loop(hours=24)
    async def daily_challenge_report(self) -> None:
        try:
            channel = await resolve_messageable(
                self.bot, self.settings.alpacahack_channel_id
            )
            if channel is None:
                return
            challenge = await asyncio.to_thread(self.client.fetch_daily_challenge)
            if challenge is None:
                return
            reserved = await asyncio.to_thread(
                self.db.reserve_alpacahack_daily_notification,
                challenge.url,
            )
            if reserved:
                await send_safely(
                    channel,
                    embed=_build_daily_embed(challenge),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except Exception:
            logger.exception("Error in daily_challenge_report")

    @daily_challenge_report.before_loop
    async def before_daily_challenge(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def weekly_solve_report(self) -> None:
        try:
            if datetime.datetime.now(self.settings.tzinfo).weekday() != 6:
                return
            channel = await resolve_messageable(
                self.bot, self.settings.alpacahack_channel_id
            )
            if channel is None:
                return
            summary = await asyncio.to_thread(
                collect_weekly_summary,
                self.db,
                self.client,
                timezone=self.settings.tzinfo,
            )
            await send_safely(channel, embed=_build_summary_embed(summary))
        except Exception:
            logger.exception("Error in weekly_solve_report")

    @weekly_solve_report.before_loop
    async def before_weekly_solve(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(name="add", description="AlpacaHackユーザーを登録します。")
    @app_commands.describe(username="AlpacaHackのユーザー名")
    async def add_user(self, interaction: discord.Interaction, username: str) -> None:
        if interaction.guild is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        name = username.strip()
        if not name:
            await send_interaction(interaction, "ユーザー名が空です。")
            return
        if len(name) > _MAX_USERNAME_LENGTH or not _USERNAME_PATTERN.fullmatch(name):
            await send_interaction(
                interaction,
                "ユーザー名は 32 文字以内の英数字と `-` `_` で入力してください。",
            )
            return
        try:
            created = await asyncio.to_thread(
                self.db.add_alpacahack_user, name, max_users=_MAX_USERS
            )
        except ConflictError:
            await send_interaction(interaction, "登録数が上限(50人)に達しています。")
            return
        if created:
            await send_interaction(interaction, f"`{name}` を登録しました。")
            await log_audit(
                self.bot,
                interaction,
                command_name="alpaca add",
                details=[f"ユーザー名: {name}"],
            )
        else:
            await send_interaction(interaction, f"`{name}` は既に登録されています。")

    @app_commands.command(
        name="del", description="AlpacaHackユーザーの登録を削除します。"
    )
    @app_commands.describe(username="AlpacaHackのユーザー名")
    async def del_user(self, interaction: discord.Interaction, username: str) -> None:
        if interaction.guild is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        name = username.strip()
        if not name:
            await send_interaction(interaction, "ユーザー名が空です。")
            return
        deleted = await asyncio.to_thread(self.db.delete_alpacahack_user, name)
        if deleted:
            await send_interaction(interaction, f"`{name}` の登録を削除しました。")
            await log_audit(
                self.bot,
                interaction,
                command_name="alpaca del",
                details=[f"ユーザー名: {name}"],
            )
        else:
            await send_interaction(interaction, f"`{name}` は登録されていません。")

    @app_commands.command(
        name="list", description="登録済みAlpacaHackユーザー一覧を表示します。"
    )
    async def list_users(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        users = await asyncio.to_thread(self.db.list_alpacahack_users)
        if not users:
            await send_interaction(interaction, "登録ユーザーはいません。")
            return
        lines = [f"- {user}" for user in users]
        await send_interaction(
            interaction, f"登録ユーザー ({len(users)}人):\n" + "\n".join(lines)
        )

    @app_commands.command(name="solve", description="今週のsolve状況を表示します。")
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: i.guild_id)
    async def show_solves(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        await interaction.response.defer()
        summary = await asyncio.to_thread(
            collect_weekly_summary,
            self.db,
            self.client,
            timezone=self.settings.tzinfo,
        )
        await interaction.followup.send(embed=_build_summary_embed(summary))

    @app_commands.command(name="daily", description="現在のDaily問題を表示します。")
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: i.guild_id)
    async def show_daily(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        await interaction.response.defer()
        try:
            challenge = await asyncio.to_thread(self.client.fetch_daily_challenge)
        except ExternalAPIError:
            await send_interaction(
                interaction,
                "AlpacaHack からの取得に失敗しました。",
                ephemeral=False,
            )
            return
        if challenge is None:
            await send_interaction(
                interaction,
                "公開中の Daily AlpacaHack 問題はありません。",
                ephemeral=False,
            )
            return
        await interaction.followup.send(embed=_build_daily_embed(challenge))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Alpacahack(bot))
