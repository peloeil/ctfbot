import datetime
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from ctfbot.db import Database
from ctfbot.errors import ExternalAPIError

_MAX_PAGES = 20
_PAGE_SIZE = 10
_DAILY_URL = "https://alpacahack.com/daily"
_DAILY_CHALLENGE_PATH = re.compile(r"^/daily/challenges/[^/]+$")
_DAILY_RELEASE_AT = re.compile(r'\\"releaseAt\\",\[\\"D\\",(\d+)\]')
_DAILY_ACTIVE_ENDS_AT = re.compile(r'\\"activeEndsAt\\",\\"([^"\\]+)\\"')
_ATTACHMENT_URL_PREFIX = "https://alpacahack-prod.s3.ap-northeast-1.amazonaws.com/"


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


@dataclass(frozen=True, slots=True)
class DailyChallenge:
    title: str
    url: str
    author: str
    categories: tuple[str, ...]
    difficulty: str
    description: str
    attachment_urls: tuple[str, ...]
    starts_at: datetime.datetime
    ends_at: datetime.datetime


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

    def fetch_daily_challenge(self) -> DailyChallenge | None:
        index_html = self._get_html(_DAILY_URL)
        index = BeautifulSoup(index_html, "html.parser")
        label = index.find(
            string=lambda value: bool(
                value and value.strip().lower() == "today's challenge"
            )
        )
        if label is None:
            raise ExternalAPIError("Unexpected Daily AlpacaHack page.")
        container = label.find_parent("div")
        if not isinstance(container, Tag):
            raise ExternalAPIError("Unexpected Daily AlpacaHack page.")
        card = container.find(
            "a", href=lambda value: bool(value and _DAILY_CHALLENGE_PATH.match(value))
        )
        if not isinstance(card, Tag):
            return None
        parts = [
            text.strip()
            for text in card.find_all(string=True)
            if text.parent
            and text.parent.name not in {"script", "style"}
            and text.strip()
        ]
        if len(parts) < 5:
            raise ExternalAPIError("Unexpected Daily AlpacaHack challenge card.")
        challenge_url = urljoin(_DAILY_URL, str(card["href"]))
        challenge_html = self._get_html(challenge_url)
        page = BeautifulSoup(challenge_html, "html.parser")
        heading = page.find("h1")
        if not isinstance(heading, Tag):
            raise ExternalAPIError("Unexpected Daily AlpacaHack challenge page.")
        title = " ".join(heading.get_text(" ", strip=True).split())
        description = _parse_daily_description(heading, page)
        attachment_urls = tuple(
            dict.fromkeys(
                str(link["href"])
                for link in page.find_all("a", href=True)
                if str(link["href"]).startswith(_ATTACHMENT_URL_PREFIX)
            )
        )
        starts_at, ends_at = _parse_daily_period(
            index_html,
            challenge_html,
            timezone=self._timezone,
        )
        return DailyChallenge(
            title=title,
            url=challenge_url,
            author=parts[0],
            categories=tuple(parts[2:-2]),
            difficulty=parts[-2],
            description=description,
            attachment_urls=attachment_urls,
            starts_at=starts_at,
            ends_at=ends_at,
        )

    def _get_html(self, url: str, *, params: dict[str, int] | None = None) -> str:
        try:
            response = requests.get(url, params=params, timeout=self._timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ExternalAPIError("AlpacaHack からの取得に失敗しました。") from exc
        return response.text

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
            html = self._get_html(
                f"https://alpacahack.com/users/{username}/solved-challenges",
                params=params,
            )
            page_records = self._parse_html(html)
            records.extend(page_records)
            if len(page_records) < _PAGE_SIZE:
                break
            if since and page_records[-1].solved_at.date() < since:
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
            challenge_name = " ".join(
                (link or cells[0]).get_text(" ", strip=True).split()
            )
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


def _parse_daily_period(
    index_html: str,
    challenge_html: str,
    *,
    timezone: datetime.tzinfo,
) -> tuple[datetime.datetime, datetime.datetime]:
    release = _DAILY_RELEASE_AT.search(challenge_html)
    end = _DAILY_ACTIVE_ENDS_AT.search(index_html)
    if release is None or end is None:
        raise ExternalAPIError("Unexpected Daily AlpacaHack period data.")
    try:
        starts_at = datetime.datetime.fromtimestamp(
            int(release.group(1)) / 1000,
            datetime.UTC,
        ).astimezone(timezone)
        ends_at = datetime.datetime.fromisoformat(
            end.group(1).replace("Z", "+00:00")
        ).astimezone(timezone)
    except (OverflowError, ValueError) as exc:
        raise ExternalAPIError("Unexpected Daily AlpacaHack period data.") from exc
    if starts_at >= ends_at:
        raise ExternalAPIError("Unexpected Daily AlpacaHack period data.")
    return starts_at, ends_at


def _parse_daily_description(heading: Tag, page: BeautifulSoup) -> str:
    first_markdown_element = heading.find_next(attrs={"node": True})
    if isinstance(first_markdown_element, Tag) and isinstance(
        first_markdown_element.parent, Tag
    ):
        blocks = []
        for child in first_markdown_element.parent.find_all(recursive=False):
            if child.name in {"script", "style"}:
                continue
            text = " ".join(child.stripped_strings)
            summary = child.find("summary") if child.name == "details" else None
            if isinstance(summary, Tag):
                label = " ".join(summary.stripped_strings)
                body = text.removeprefix(label).strip()
                text = f"{label}\n||{body}||" if body else label
            blocks.append(text)
        description = "\n\n".join(block for block in blocks if block)
        if description:
            return description
    meta = page.find("meta", attrs={"name": "description"})
    if isinstance(meta, Tag):
        return str(meta.get("content", "")).strip()
    return ""


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


def _parse_solved_at(value: str, timezone: datetime.tzinfo) -> datetime.datetime | None:
    match = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)", value)
    if match is None:
        return None
    date_str = match.group(1).replace("/", "-")
    raw = f"{date_str} {match.group(2)}"
    fmt = "%Y-%m-%d %H:%M:%S" if raw.count(":") == 2 else "%Y-%m-%d %H:%M"
    try:
        parsed = datetime.datetime.strptime(raw, fmt).replace(tzinfo=datetime.UTC)
    except ValueError:
        return None
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
