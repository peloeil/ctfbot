from __future__ import annotations

import datetime
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from .errors import ConfigurationError


class ConfigError(ConfigurationError):
    """Backward-compatible alias for configuration errors."""


def _read_required_str(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required.")
    return value


def _read_int(environ: Mapping[str, str], name: str, default: int = 0) -> int:
    raw_value = environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer: {raw_value!r}") from exc


def _read_log_level(environ: Mapping[str, str]) -> str:
    value = environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if value not in allowed:
        raise ConfigError(f"LOG_LEVEL must be one of {sorted(allowed)}: {value!r}")
    return value


def _read_user_agent(environ: Mapping[str, str]) -> str:
    value = environ.get("CTFTIME_USER_AGENT", "").strip()
    if value:
        return value
    return "ctfbot/2.0 (+discord)"


def _read_clock_time(
    environ: Mapping[str, str],
    name: str,
    default: str,
    *,
    tzinfo: datetime.tzinfo,
) -> datetime.time:
    value = environ.get(name, default).strip() or default
    try:
        hour_str, minute_str = value.split(":", maxsplit=1)
        hour = int(hour_str)
        minute = int(minute_str)
    except ValueError as exc:
        raise ConfigError(f"{name} must be in HH:MM format: {value!r}") from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError(f"{name} must be a valid 24h time: {value!r}")

    return datetime.time(hour=hour, minute=minute, tzinfo=tzinfo)


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
    alpacahack_solve_time: datetime.time
    ctftime_notification_time: datetime.time
    ctftime_window_days: int
    ctftime_event_limit: int
    ctftime_user_agent: str


def load_settings(
    *,
    dotenv_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    load_dotenv(dotenv_path=dotenv_path)
    env = os.environ if environ is None else environ

    timezone = env.get("TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo"
    try:
        tzinfo = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"TIMEZONE is invalid: {timezone!r}") from exc

    database_path = env.get("DATABASE_PATH", "alpaca.db").strip() or "alpaca.db"
    database_parent = Path(database_path).expanduser().resolve().parent
    if not database_parent.exists():
        raise ConfigError(f"DATABASE_PATH directory does not exist: {database_parent}")

    command_prefix = env.get("COMMAND_PREFIX", "!").strip() or "!"

    return Settings(
        discord_token=_read_required_str(env, "DISCORD_TOKEN"),
        command_prefix=command_prefix,
        bot_channel_id=_read_int(env, "BOT_CHANNEL_ID"),
        bot_status_channel_id=_read_int(env, "BOT_STATUS_CHANNEL_ID"),
        timezone=timezone,
        tzinfo=tzinfo,
        log_level=_read_log_level(env),
        database_path=database_path,
        alpacahack_solve_time=_read_clock_time(
            env, "ALPACAHACK_SOLVE_TIME", "23:00", tzinfo=tzinfo
        ),
        ctftime_notification_time=_read_clock_time(
            env, "CTFTIME_NOTIFICATION_TIME", "09:00", tzinfo=tzinfo
        ),
        ctftime_window_days=_read_int(env, "CTFTIME_WINDOW_DAYS", default=14),
        ctftime_event_limit=_read_int(env, "CTFTIME_EVENT_LIMIT", default=20),
        ctftime_user_agent=_read_user_agent(env),
    )
