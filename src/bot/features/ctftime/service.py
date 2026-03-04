from __future__ import annotations

import datetime
import time
from collections.abc import Callable

import requests

from ...errors import ExternalAPIError
from ...utils.helpers import logger
from .models import CTFEvent

API_URL = "https://ctftime.org/api/v1/events/"
REQUEST_TIMEOUT_SECONDS = 10
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5


class CTFTimeService:
    def __init__(
        self,
        *,
        timezone: datetime.tzinfo,
        user_agent: str,
        api_url: str = API_URL,
        request_timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
        max_retries: int = MAX_RETRIES,
        retry_backoff_seconds: float = RETRY_BACKOFF_SECONDS,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._timezone = timezone
        self._user_agent = user_agent
        self._api_url = api_url
        self._request_timeout_seconds = request_timeout_seconds
        self._max_retries = max(1, max_retries)
        self._retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._sleep = sleep_fn

    def get_upcoming_events(self, days: int, limit: int) -> list[CTFEvent]:
        payload = self._request_events(days=days, limit=limit)
        parsed_events: list[CTFEvent] = []
        for item in payload:
            start = self._parse_iso_datetime(item.get("start"))
            finish_at = self._parse_iso_datetime(item.get("finish"))
            if start is None or finish_at is None:
                continue

            title_obj = item.get("title")
            url_obj = item.get("url")
            if not isinstance(title_obj, str) or not isinstance(url_obj, str):
                continue

            parsed_events.append(
                CTFEvent(
                    title=title_obj,
                    start=start,
                    finish=finish_at,
                    ctftime_url=url_obj,
                )
            )

        return parsed_events

    def _request_events(self, *, days: int, limit: int) -> list[dict[str, object]]:
        now = int(time.time())
        finish = now + (max(days, 1) * 24 * 60 * 60)
        headers = {"User-Agent": self._user_agent}
        params = {"limit": max(limit, 1), "start": now, "finish": finish}

        last_error: requests.RequestException | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = requests.get(
                    self._api_url,
                    headers=headers,
                    params=params,
                    timeout=self._request_timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, list):
                    return [item for item in payload if isinstance(item, dict)]

                logger.warning("Unexpected CTFtime payload type: %s", type(payload))
                return []
            except requests.RequestException as error:
                last_error = error
                logger.exception(
                    "Failed to fetch CTFtime events (attempt %s/%s)",
                    attempt,
                    self._max_retries,
                )
                if attempt < self._max_retries and self._retry_backoff_seconds > 0:
                    self._sleep(self._retry_backoff_seconds * attempt)

        if last_error is not None:
            raise ExternalAPIError("Failed to fetch CTFtime events.") from last_error
        raise ExternalAPIError("Failed to fetch CTFtime events.")

    def _parse_iso_datetime(self, raw_value: object) -> datetime.datetime | None:
        if not isinstance(raw_value, str) or not raw_value:
            return None

        normalized = raw_value.replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(normalized)
        except ValueError:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.UTC)

        return dt.astimezone(self._timezone)
