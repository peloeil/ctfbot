from __future__ import annotations

import datetime
from collections.abc import Generator
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, element
from requests import RequestException

from ...errors import ExternalAPIError
from ...utils.helpers import format_code_block, handle_error, logger

ALPACAHACK_BASE_URL = "https://alpacahack.com/users/"
REQUEST_TIMEOUT_SECONDS = 10
UTC = ZoneInfo("UTC")


@dataclass(frozen=True, slots=True)
class SolveRecord:
    challenge: str
    solved_at: datetime.datetime


def is_leaf(tag: element.Tag) -> bool:
    return all(not isinstance(child, element.Tag) for child in tag.children)


@dataclass(frozen=True, slots=True)
class AlpacaHackService:
    timezone: datetime.tzinfo
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
        today = reference_date or datetime.datetime.now(self.timezone).date()
        week_start, _ = self.get_week_range(today)

        records = self._get_solve_records(user)
        if not records:
            return []

        challenges: list[str] = []
        seen: set[str] = set()
        for record in records:
            solved_date = record.solved_at.date()
            if solved_date < week_start or solved_date > today:
                continue
            if record.challenge in seen:
                continue
            seen.add(record.challenge)
            challenges.append(record.challenge)
        return challenges

    def get_alpacahack_solves(self, user: str) -> str:
        try:
            logger.info("Fetching solve information for user: %s", user)
            soup = self._fetch_user_page(user)
            tbody = self._extract_solved_challenges_tbody(soup)
            if not isinstance(tbody, element.Tag):
                logger.warning("No data found for user: %s", user)
                return format_code_block(f"No data found for user: {user}")

            result: list[str] = []
            result.append(user)
            result.append(f"{'CHALLENGE':20}{'SOLVES':20}{'SOLVED AT':20}")
            for row in tbody.find_all("tr"):
                if not isinstance(row, element.Tag):
                    continue
                data = row.find_all("td")
                if len(data) < 3:
                    continue
                challenge = data[0].get_text(strip=True)
                solves = data[1].get_text(strip=True)
                solve_at = data[2].get_text(strip=True)
                result.append(f"{challenge:20}{solves:20}{solve_at:20}")

            logger.info("Successfully fetched solve information for user: %s", user)
            return format_code_block("\n".join(result))
        except Exception as error:
            logger.error(
                "Error fetching solve information for user %s: %s", user, error
            )
            return format_code_block(
                handle_error(error, f"Failed to get solves for {user}")
            )

    def get_alpacahack_info(self, user: str) -> Generator[str, None, None]:
        try:
            logger.info("Fetching detailed information for user: %s", user)
            soup = self._fetch_user_page(user)
            root_container = soup.find("div", class_="MuiContainer-root")
            if not isinstance(root_container, element.Tag):
                logger.warning("No data container found for user: %s", user)
                yield "No data found"
                return

            section_count = 0
            for section in root_container.contents[1:]:
                if not isinstance(section, element.Tag):
                    continue

                tbody = section.find("tbody", class_="MuiTableBody-root")
                if not isinstance(tbody, element.Tag):
                    continue
                thead = section.find("thead")
                if not isinstance(thead, element.Tag):
                    continue
                header_title = section.find("p", class_="MuiTypography-root")
                if header_title is None:
                    continue

                section_count += 1
                result: list[str] = []
                result.append(f"{header_title.text.center(50, '-')}")
                header_row = thead.find("tr")
                if not isinstance(header_row, element.Tag):
                    continue

                header_cells = header_row.find_all("th")
                result.append(
                    "".join(
                        cell.get_text(strip=True).ljust(20) for cell in header_cells
                    )
                )

                for row in tbody.find_all("tr"):
                    if not isinstance(row, element.Tag):
                        continue
                    data = row.find_all("td")
                    row_text: list[str] = []
                    for cell in data:
                        if not isinstance(cell, element.Tag):
                            continue
                        leaf_values: list[str] = []
                        for child_tag in cell.find_all():
                            if not isinstance(child_tag, element.Tag):
                                continue
                            if is_leaf(child_tag) and child_tag.name != "style":
                                leaf_values.append(child_tag.get_text(strip=True))
                        leaf_texts = " ".join(leaf_values)
                        row_text.append(leaf_texts.ljust(20))
                    result.append("".join(row_text))

                yield "\n".join(result)
            logger.info(
                "Successfully fetched %s sections for user: %s", section_count, user
            )
        except Exception as error:
            logger.error(
                "Error fetching detailed information for user %s: %s", user, error
            )
            yield handle_error(error, f"Failed to get info for {user}")

    def _get_solve_records(self, user: str) -> list[SolveRecord]:
        try:
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

                challenge = challenge_tag.get_text(strip=True)
                if not challenge:
                    continue
                records.append(SolveRecord(challenge=challenge, solved_at=solved_at))

            return records
        except ExternalAPIError:
            logger.exception("Failed to fetch weekly solve records for user: %s", user)
            return []

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

        normalized = raw_value.strip().removesuffix(" UTC")
        try:
            naive = datetime.datetime.strptime(normalized, "%Y-%m-%d %H:%M")
        except ValueError:
            return None

        return naive.replace(tzinfo=UTC).astimezone(self.timezone)

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
