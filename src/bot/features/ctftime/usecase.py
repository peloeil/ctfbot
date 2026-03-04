from __future__ import annotations

from .models import CTFEvent
from .service import CTFTimeService


class CTFTimeUseCase:
    def __init__(
        self,
        service: CTFTimeService,
        *,
        window_days: int,
        event_limit: int,
    ) -> None:
        self._service = service
        self._window_days = max(1, window_days)
        self._event_limit = max(1, event_limit)

    def get_upcoming_events(self) -> list[CTFEvent]:
        return self._service.get_upcoming_events(
            days=self._window_days,
            limit=self._event_limit,
        )
