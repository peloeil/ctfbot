from __future__ import annotations

import datetime
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ...application.alpacahack import (
    SolveRecord,
    get_week_range,
    select_weekly_solves,
)
from ...errors import ExternalAPIError
from ...log import logger
from .models import SolvedChallenge, UserMutationResult
from .repository import AlpacaHackUserRepository


@dataclass(frozen=True, slots=True)
class WeeklySolveSummary:
    week_start: datetime.date
    week_end: datetime.date
    total_users: int
    weekly_solves: dict[str, list[SolvedChallenge]]
    failed_users: list[str]


@dataclass(frozen=True, slots=True)
class WeeklySolveFetchResult:
    challenges: list[SolvedChallenge]
    fetch_failed: bool = False


class AlpacaHackSolveRecordClient(Protocol):
    def fetch_solve_records(self, user: str) -> list[SolveRecord]: ...


class AlpacaHackUseCase:
    def __init__(
        self,
        repository: AlpacaHackUserRepository,
        client: AlpacaHackSolveRecordClient,
        *,
        timezone: datetime.tzinfo,
        request_interval_seconds: float = 0.2,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._repository = repository
        self._client = client
        self._timezone = timezone
        self._request_interval_seconds = max(0.0, request_interval_seconds)
        self._sleep = sleep_fn

    def add_user(self, name: str) -> UserMutationResult:
        return self._repository.add_user(name)

    def delete_user(self, name: str) -> UserMutationResult:
        return self._repository.delete_user(name)

    def list_usernames(self) -> list[str]:
        return self._repository.list_usernames()

    def collect_weekly_summary(
        self, reference_date: datetime.date | None = None
    ) -> WeeklySolveSummary:
        today = reference_date or datetime.datetime.now(self._timezone).date()
        week_start, week_end = get_week_range(today)
        users = self._repository.list_usernames()

        weekly_solves: dict[str, list[SolvedChallenge]] = {}
        failed_users: list[str] = []
        for username in users:
            result = self.collect_weekly_solve_result(username, reference_date=today)
            if result.fetch_failed:
                failed_users.append(username)
            elif result.challenges:
                weekly_solves[username] = result.challenges
            if self._request_interval_seconds > 0:
                self._sleep(self._request_interval_seconds)

        return WeeklySolveSummary(
            week_start=week_start,
            week_end=week_end,
            total_users=len(users),
            weekly_solves=weekly_solves,
            failed_users=failed_users,
        )

    def collect_weekly_solve_result(
        self, user: str, reference_date: datetime.date | None = None
    ) -> WeeklySolveFetchResult:
        today = reference_date or datetime.datetime.now(self._timezone).date()
        try:
            records = self._client.fetch_solve_records(user)
        except ExternalAPIError:
            logger.warning("Failed to fetch weekly solve records for user: %s", user)
            return WeeklySolveFetchResult(challenges=[], fetch_failed=True)

        challenges = [
            SolvedChallenge(name=challenge.name, url=challenge.url)
            for challenge in select_weekly_solves(records, today=today)
        ]
        return WeeklySolveFetchResult(
            challenges=challenges,
        )
