from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, element
from requests import RequestException

from ...errors import ExternalAPIError
from ...utils.helpers import logger
from .models import SolvedChallenge

ALPACAHACK_SITE_URL = "https://alpacahack.com/"
ALPACAHACK_BASE_URL = urljoin(ALPACAHACK_SITE_URL, "users/")
REQUEST_TIMEOUT_SECONDS = 10
UTC = ZoneInfo("UTC")
ARIA_LABEL_DATETIME_PATTERN = re.compile(
    r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)"
)


@dataclass(frozen=True, slots=True)
class SolveRecord:
    challenge: SolvedChallenge
    solved_at: datetime.datetime


@dataclass(frozen=True, slots=True)
class WeeklySolveFetchResult:
    challenges: list[SolvedChallenge]
    fetch_failed: bool = False


@dataclass(frozen=True, slots=True)
class AlpacaHackService:
    timezone: datetime.tzinfo
    site_url: str = ALPACAHACK_SITE_URL
    base_url: str = ALPACAHACK_BASE_URL
    request_timeout_seconds: int = REQUEST_TIMEOUT_SECONDS

    def get_week_range(
        self, reference_date: datetime.date | None = None
    ) -> tuple[datetime.date, datetime.date]:
        today = reference_date or datetime.datetime.now(self.timezone).date()
        week_start = today - datetime.timedelta(days=today.weekday())
        week_end = week_start + datetime.timedelta(days=6)
        return week_start, week_end

    def get_weekly_solve_challenges(
        self, user: str, reference_date: datetime.date | None = None
    ) -> list[str]:
        return [
            challenge.name
            for challenge in self.collect_weekly_solve_result(
                user=user,
                reference_date=reference_date,
            ).challenges
        ]

    def collect_weekly_solve_result(
        self, user: str, reference_date: datetime.date | None = None
    ) -> WeeklySolveFetchResult:
        today = reference_date or datetime.datetime.now(self.timezone).date()
        week_start, _ = self.get_week_range(today)

        try:
            records = self._get_solve_records(user)
        except ExternalAPIError:
            logger.warning("Failed to fetch weekly solve records for user: %s", user)
            return WeeklySolveFetchResult(challenges=[], fetch_failed=True)
        if not records:
            return WeeklySolveFetchResult(challenges=[])

        challenges: list[SolvedChallenge] = []
        seen: set[str] = set()
        for record in records:
            solved_date = record.solved_at.date()
            if solved_date < week_start or solved_date > today:
                continue
            challenge_key = record.challenge.url or record.challenge.name
            if challenge_key in seen:
                continue
            seen.add(challenge_key)
            challenges.append(record.challenge)
        return WeeklySolveFetchResult(challenges=challenges)

    def _get_solve_records(self, user: str) -> list[SolveRecord]:
        logger.info("Fetching weekly solve records for user: %s", user)
        soup = self._fetch_user_page(user)
        tbody = self._extract_solved_challenges_tbody(soup)
        if not isinstance(tbody, element.Tag):
            return []

        records: list[SolveRecord] = []
        for row in tbody.find_all("tr"):
            if not isinstance(row, element.Tag):
                continue
            columns = row.find_all("td")
            if len(columns) < 3:
                continue

            challenge_cell = columns[0]
            solved_at_cell = columns[2]
            if not isinstance(challenge_cell, element.Tag):
                continue
            if not isinstance(solved_at_cell, element.Tag):
                continue

            challenge_tag = challenge_cell.find("a")
            solved_at_tag = solved_at_cell.find("span")
            if not isinstance(challenge_tag, element.Tag):
                continue
            if not isinstance(solved_at_tag, element.Tag):
                continue

            solved_at = self._parse_aria_label_to_local_datetime(
                solved_at_tag.get("aria-label")
            )
            if solved_at is None:
                continue

            challenge_name = challenge_tag.get_text(strip=True)
            if not challenge_name:
                continue
            records.append(
                SolveRecord(
                    challenge=SolvedChallenge(
                        name=challenge_name,
                        url=self._resolve_challenge_url(challenge_tag.get("href")),
                    ),
                    solved_at=solved_at,
                )
            )

        return records

    def _extract_solved_challenges_tbody(
        self, soup: BeautifulSoup
    ) -> element.Tag | None:
        for paragraph in soup.find_all("p"):
            if paragraph.get_text(strip=True) == "SOLVED CHALLENGES":
                sibling = paragraph.find_next_sibling("div")
                if isinstance(sibling, element.Tag):
                    tbody = sibling.find("tbody")
                    if isinstance(tbody, element.Tag):
                        return tbody

        fallback = soup.find("tbody", class_="MuiTableBody-root")
        if isinstance(fallback, element.Tag):
            return fallback
        return None

    def _parse_aria_label_to_local_datetime(
        self, raw_value: object
    ) -> datetime.datetime | None:
        if not isinstance(raw_value, str) or not raw_value:
            return None

        match = ARIA_LABEL_DATETIME_PATTERN.search(raw_value.strip())
        if match is None:
            return None

        normalized = f"{match.group(1)} {match.group(2)}"
        date_format = (
            "%Y-%m-%d %H:%M:%S" if normalized.count(":") == 2 else "%Y-%m-%d %H:%M"
        )
        try:
            naive = datetime.datetime.strptime(normalized, date_format)
        except ValueError:
            return None

        return naive.replace(tzinfo=UTC).astimezone(self.timezone)

    def _resolve_challenge_url(self, raw_value: object) -> str | None:
        if not isinstance(raw_value, str):
            return None
        href = raw_value.strip()
        if not href:
            return None
        return urljoin(self.site_url, href)

    def _fetch_user_page(self, user: str) -> BeautifulSoup:
        try:
            response = requests.get(
                f"{self.base_url}{user}",
                timeout=self.request_timeout_seconds,
            )
            response.raise_for_status()
        except RequestException as error:
            raise ExternalAPIError(
                f"Failed to fetch AlpacaHack page for {user}"
            ) from error

        return BeautifulSoup(response.content, features="html.parser")
