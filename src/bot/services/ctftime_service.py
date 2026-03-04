from __future__ import annotations

import datetime
import time
from dataclasses import dataclass

import requests

from ..config import settings
from ..utils.helpers import logger

API_URL = "https://ctftime.org/api/v1/events/"
REQUEST_TIMEOUT_SECONDS = 10
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.5


@dataclass(frozen=True, slots=True)
class CTFEvent:
    title: str
    start: datetime.datetime
    finish: datetime.datetime
    ctftime_url: str


def get_upcoming_events(days: int, limit: int) -> list[CTFEvent]:
    now = int(time.time())
    finish = now + (max(days, 1) * 24 * 60 * 60)

    headers = {"User-Agent": settings.ctftime_user_agent}
    params = {"limit": max(limit, 1), "start": now, "finish": finish}

    payload = _request_events(headers=headers, params=params)
    if not payload:
        return []

    parsed_events: list[CTFEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            continue

        start = _parse_iso_datetime(item.get("start"))
        finish_at = _parse_iso_datetime(item.get("finish"))
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


def _request_events(
    headers: dict[str, str], params: dict[str, int]
) -> list[dict[str, object]]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                API_URL,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]

            logger.warning("Unexpected CTFtime payload type: %s", type(payload))
            return []
        except requests.RequestException:
            logger.exception(
                "Failed to fetch CTFtime events (attempt %s/%s)",
                attempt,
                MAX_RETRIES,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    return []


def _parse_iso_datetime(raw_value: object) -> datetime.datetime | None:
    if not isinstance(raw_value, str) or not raw_value:
        return None

    normalized = raw_value.replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)

    return dt.astimezone(settings.tzinfo)
