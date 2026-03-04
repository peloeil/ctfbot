from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when environment configuration is missing or invalid."""


def _read_required_str(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required.")
    return value


def _read_int(name: str, default: int = 0) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer: {raw_value!r}") from exc


def _read_log_level() -> str:
    value = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if value not in allowed:
        raise ConfigError(f"LOG_LEVEL must be one of {sorted(allowed)}: {value!r}")
    return value


def _read_user_agent() -> str:
    value = os.getenv("CTFTIME_USER_AGENT", "").strip()
    if value:
        return value
    return "ctfbot/2.0 (+discord)"


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    command_prefix: str
    bot_channel_id: int
    bot_status_channel_id: int
    timezone: str
    tzinfo: ZoneInfo
    log_level: str
    database_path: str
    alpacahack_solve_time: str
    ctftime_notification_time: str
    ctftime_window_days: int
    ctftime_event_limit: int
    ctftime_user_agent: str


def load_settings() -> Settings:
    load_dotenv()

    timezone = os.getenv("TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo"
    try:
        tzinfo = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"TIMEZONE is invalid: {timezone!r}") from exc

    database_path = os.getenv("DATABASE_PATH", "alpaca.db").strip() or "alpaca.db"
    database_parent = Path(database_path).expanduser().resolve().parent
    if not database_parent.exists():
        raise ConfigError(f"DATABASE_PATH directory does not exist: {database_parent}")

    command_prefix = os.getenv("COMMAND_PREFIX", "!").strip() or "!"

    return Settings(
        discord_token=_read_required_str("DISCORD_TOKEN"),
        command_prefix=command_prefix,
        bot_channel_id=_read_int("BOT_CHANNEL_ID"),
        bot_status_channel_id=_read_int("BOT_STATUS_CHANNEL_ID"),
        timezone=timezone,
        tzinfo=tzinfo,
        log_level=_read_log_level(),
        database_path=database_path,
        alpacahack_solve_time=os.getenv("ALPACAHACK_SOLVE_TIME", "23:00").strip()
        or "23:00",
        ctftime_notification_time=os.getenv(
            "CTFTIME_NOTIFICATION_TIME", "09:00"
        ).strip()
        or "09:00",
        ctftime_window_days=_read_int("CTFTIME_WINDOW_DAYS", default=14),
        ctftime_event_limit=_read_int("CTFTIME_EVENT_LIMIT", default=20),
        ctftime_user_agent=_read_user_agent(),
    )


settings = load_settings()
