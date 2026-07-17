import asyncio
import datetime
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urljoin

import discord
import requests
from bs4 import BeautifulSoup, Tag
from discord import app_commands
from discord.ext import commands, tasks

from bot.db import Database
from bot.errors import ExternalAPIError
from bot.helpers import log_audit, resolve_messageable, send_interaction, send_safely
from bot.log import logger
from bot.runtime import get_runtime

MAX_EMBED_FIELDS = 25
ALPACAHACK_EMBED_COLOR = 0xFD8028
_MAX_PAGES = 20
_PAGE_SIZE = 10


@dataclass(frozen=True, slots=True)
class SolveRecord:
    challenge_name: str
    challenge_url: str | None
    solved_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class WeeklySolveSummary:
    week_start: datetime.date
    week_end: datetime.date
    total_users: int
    weekly_solves: dict[str, list[SolveRecord]]
    failed_users: list[str]


def get_week_range(
    reference_date: datetime.date,
) -> tuple[datetime.date, datetime.date]:
    week_start = reference_date - datetime.timedelta(days=reference_date.weekday())
    return week_start, week_start + datetime.timedelta(days=6)


def select_weekly_solves(
    records: Sequence[SolveRecord],
    *,
    week_start: datetime.date,
    week_end: datetime.date,
) -> list[SolveRecord]:
    selected: dict[str, SolveRecord] = {}
    for record in sorted(records, key=lambda item: item.solved_at):
        solved_date = record.solved_at.date()
        if not week_start <= solved_date <= week_end:
            continue
        key = record.challenge_url or record.challenge_name
        selected.setdefault(key, record)
    return sorted(selected.values(), key=lambda item: item.solved_at)


class AlpacaHackClient:
    def __init__(self, *, timezone: datetime.tzinfo, request_timeout: int = 10) -> None:
        self._timezone = timezone
        self._timeout = request_timeout

    def fetch_solve_records(
        self,
        username: str,
        *,
        since: datetime.date | None = None,
        page_interval: float = 0.2,
    ) -> list[SolveRecord]:
        records: list[SolveRecord] = []
        for page in range(1, _MAX_PAGES + 1):
            if page > 1:
                time.sleep(page_interval)
            params: dict[str, int] = {}
            if page > 1:
                params["solvesPage"] = page
            try:
                response = requests.get(
                    f"https://alpacahack.com/users/{username}/solved-challenges",
                    params=params,
                    timeout=self._timeout,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                raise ExternalAPIError("AlpacaHack からの取得に失敗しました。") from exc
            page_records = self._parse_html(response.text)
            records.extend(page_records)
            if len(page_records) < _PAGE_SIZE:
                break
            if since and page_records and page_records[-1].solved_at.date() < since:
                break
        return records

    def _parse_html(self, html: str) -> list[SolveRecord]:
        soup = BeautifulSoup(html, "html.parser")
        table = _find_solved_challenges_table(soup)
        if table is None:
            return []
        records: list[SolveRecord] = []
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            link = cells[0].find("a")
            challenge_name = _tag_text(link or cells[0])
            if not challenge_name:
                continue
            href = link.get("href") if isinstance(link, Tag) else None
            challenge_url = (
                urljoin("https://alpacahack.com", str(href)) if href else None
            )
            ts_cell = cells[2]
            aria_el = ts_cell.find(True, attrs={"aria-label": True})
            aria_label = (
                aria_el["aria-label"]
                if isinstance(aria_el, Tag)
                else ts_cell.get_text(" ", strip=True)
            )
            solved_at = _parse_solved_at(str(aria_label), self._timezone)
            if solved_at is None:
                continue
            records.append(
                SolveRecord(
                    challenge_name=challenge_name,
                    challenge_url=challenge_url,
                    solved_at=solved_at,
                )
            )
        return records


def _find_solved_challenges_table(soup: BeautifulSoup) -> Tag | None:
    heading = soup.find(
        string=lambda value: bool(value and "SOLVED CHALLENGES" in value.upper())
    )
    if heading is None:
        return soup.find("table")
    parent = heading.parent if isinstance(heading.parent, Tag) else None
    search_from = parent or soup
    table = search_from.find_next("table")
    return table if isinstance(table, Tag) else None


def _tag_text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split())


def _parse_solved_at(value: str, timezone: datetime.tzinfo) -> datetime.datetime | None:
    match = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)", value)
    if match is None:
        return None
    date_str = match.group(1).replace("/", "-")
    raw = f"{date_str} {match.group(2)}"
    fmt = "%Y-%m-%d %H:%M:%S" if raw.count(":") == 2 else "%Y-%m-%d %H:%M"
    parsed = datetime.datetime.strptime(raw, fmt).replace(tzinfo=datetime.UTC)
    return parsed.astimezone(timezone)


def collect_weekly_summary(
    db: Database,
    client: AlpacaHackClient,
    *,
    timezone: datetime.tzinfo,
    reference_date: datetime.date | None = None,
    request_interval: float = 0.2,
) -> WeeklySolveSummary:
    users = db.list_alpacahack_users()
    today = reference_date or datetime.datetime.now(timezone).date()
    week_start, week_end = get_week_range(today)
    weekly_solves: dict[str, list[SolveRecord]] = {}
    failed_users: list[str] = []
    for index, username in enumerate(users):
        if index:
            time.sleep(request_interval)
        try:
            records = client.fetch_solve_records(username, since=week_start)
        except ExternalAPIError:
            failed_users.append(username)
            continue
        weekly_solves[username] = select_weekly_solves(
            records, week_start=week_start, week_end=week_end
        )
    return WeeklySolveSummary(
        week_start=week_start,
        week_end=week_end,
        total_users=len(users),
        weekly_solves=weekly_solves,
        failed_users=failed_users,
    )


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
    visible_items = list(summary.weekly_solves.items())[: MAX_EMBED_FIELDS - 1]
    omitted_users = max(len(summary.weekly_solves) - len(visible_items), 0)
    for username, solves in visible_items:
        value_lines: list[str] = []
        for record in solves[:12]:
            if record.challenge_url:
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
        embed.add_field(
            name=f"{username} ({len(solves)} solves)",
            value=value,
            inline=False,
        )
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
        self.weekly_solve_report.start()

    async def cog_unload(self) -> None:
        self.weekly_solve_report.cancel()

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
        name = username.strip()
        if not name:
            await send_interaction(interaction, "ユーザー名が空です。")
            return
        created = await asyncio.to_thread(self.db.add_alpacahack_user, name)
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
        users = await asyncio.to_thread(self.db.list_alpacahack_users)
        if not users:
            await send_interaction(interaction, "登録ユーザーはいません。")
            return
        lines = [f"- {user}" for user in users]
        await send_interaction(
            interaction, f"登録ユーザー ({len(users)}人):\n" + "\n".join(lines)
        )

    @app_commands.command(name="solve", description="今週のsolve状況を表示します。")
    async def show_solves(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        summary = await asyncio.to_thread(
            collect_weekly_summary,
            self.db,
            self.client,
            timezone=self.settings.tzinfo,
        )
        await interaction.followup.send(embed=_build_summary_embed(summary))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Alpacahack(bot))
