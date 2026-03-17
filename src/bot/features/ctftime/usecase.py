from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Protocol

from .models import CTFEvent


class CTFTimeEventRecordLike(Protocol):
    title: str
    start: datetime.datetime
    finish: datetime.datetime
    ctftime_url: str


class CTFTimeEventClient(Protocol):
    def get_upcoming_events(
        self, *, days: int, limit: int
    ) -> Sequence[CTFTimeEventRecordLike]: ...


class CTFTimeUseCase:
    def __init__(
        self,
        client: CTFTimeEventClient,
        *,
        window_days: int,
        event_limit: int,
    ) -> None:
        self._client = client
        self._window_days = max(1, window_days)
        self._event_limit = max(1, event_limit)

    def get_upcoming_events(self) -> list[CTFEvent]:
        records = self._client.get_upcoming_events(
            days=self._window_days,
            limit=self._event_limit,
        )
        return [
            CTFEvent(
                title=record.title,
                start=record.start,
                finish=record.finish,
                ctftime_url=record.ctftime_url,
            )
            for record in records
        ]
