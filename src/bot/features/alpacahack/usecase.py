from __future__ import annotations

import datetime
import time
from collections.abc import Callable
from dataclasses import dataclass

from .models import UserMutationResult
from .repository import AlpacaHackUserRepository
from .service import AlpacaHackService


@dataclass(frozen=True, slots=True)
class WeeklySolveSummary:
    week_start: datetime.date
    week_end: datetime.date
    total_users: int
    weekly_solves: dict[str, list[str]]
    failed_users: list[str]


class AlpacaHackUseCase:
    def __init__(
        self,
        repository: AlpacaHackUserRepository,
        service: AlpacaHackService,
        *,
        request_interval_seconds: float = 0.2,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._repository = repository
        self._service = service
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
        today = reference_date or datetime.datetime.now(self._service.timezone).date()
        week_start, week_end = self._service.get_week_range(today)
        users = self._repository.list_usernames()

        weekly_solves: dict[str, list[str]] = {}
        failed_users: list[str] = []
        for username in users:
            result = self._service.collect_weekly_solve_result(
                username, reference_date=today
            )
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
