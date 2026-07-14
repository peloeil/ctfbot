import datetime
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from bot.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    bot_channel_id: int | None
    bot_status_channel_id: int | None
    ctf_team_category_id: int
    ctf_team_archive_category_id: int
    ctftime_channel_id: int | None
    alpacahack_channel_id: int | None
    timezone: str
    tzinfo: ZoneInfo
    log_level: str
    database_path: str
    alpacahack_solve_time: datetime.time
    ctftime_notification_time: datetime.time
    ctftime_window_days: int
    ctftime_event_limit: int
    ctftime_user_agent: str


def _read_int(environ: Mapping[str, str], name: str, default: int | None = None) -> int:
    raw = environ.get(name)
    if raw is None or raw == "":
        if default is None:
            raise ConfigurationError(f"{name} is required.")
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer.") from exc
    if value < 0:
        raise ConfigurationError(f"{name} must be non-negative.")
    return value


def _require_positive(value: int, name: str) -> int:
    if value < 1:
        raise ConfigurationError(f"{name} must be greater than 0.")
    return value


def _read_clock_time(
    environ: Mapping[str, str],
    name: str,
    default: str,
    *,
    tzinfo: datetime.tzinfo,
) -> datetime.time:
    raw = environ.get(name, default).strip()
    try:
        parsed = datetime.datetime.strptime(raw, "%H:%M")
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be HH:MM format.") from exc
    return parsed.time().replace(tzinfo=tzinfo)


def load_settings(
    *,
    dotenv_path: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    if environ is None:
        load_dotenv(dotenv_path=dotenv_path)
        env = os.environ
    else:
        env = environ

    discord_token = env.get("DISCORD_TOKEN", "").strip()
    if not discord_token:
        raise ConfigurationError("DISCORD_TOKEN is required.")

    timezone = env.get("TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo"
    try:
        tzinfo = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigurationError(f"Unknown TIMEZONE: {timezone}") from exc

    ctf_team_category_id = _read_int(env, "CTF_TEAM_CATEGORY_ID")
    if ctf_team_category_id <= 0:
        raise ConfigurationError("CTF_TEAM_CATEGORY_ID must be greater than 0.")
    ctf_team_archive_category_id = _read_int(env, "CTF_TEAM_ARCHIVE_CATEGORY_ID")
    if ctf_team_archive_category_id <= 0:
        raise ConfigurationError("CTF_TEAM_ARCHIVE_CATEGORY_ID must be greater than 0.")

    database_path = env.get("DATABASE_PATH", "ctfbot.db").strip() or "ctfbot.db"
    parent = Path(database_path).expanduser().resolve().parent
    if not parent.exists():
        raise ConfigurationError(f"DATABASE_PATH parent does not exist: {parent}")

    return Settings(
        discord_token=discord_token,
        bot_channel_id=_read_int(env, "BOT_CHANNEL_ID", 0) or None,
        bot_status_channel_id=_read_int(env, "BOT_STATUS_CHANNEL_ID", 0) or None,
        ctf_team_category_id=ctf_team_category_id,
        ctf_team_archive_category_id=ctf_team_archive_category_id,
        ctftime_channel_id=_read_int(env, "CTFTIME_CHANNEL_ID", 0) or None,
        alpacahack_channel_id=_read_int(env, "ALPACAHACK_CHANNEL_ID", 0) or None,
        timezone=timezone,
        tzinfo=tzinfo,
        log_level=env.get("LOG_LEVEL", "INFO").strip() or "INFO",
        database_path=database_path,
        alpacahack_solve_time=_read_clock_time(
            env, "ALPACAHACK_SOLVE_TIME", "23:00", tzinfo=tzinfo
        ),
        ctftime_notification_time=_read_clock_time(
            env, "CTFTIME_NOTIFICATION_TIME", "09:00", tzinfo=tzinfo
        ),
        ctftime_window_days=_require_positive(
            _read_int(env, "CTFTIME_WINDOW_DAYS", 14), "CTFTIME_WINDOW_DAYS"
        ),
        ctftime_event_limit=_require_positive(
            _read_int(env, "CTFTIME_EVENT_LIMIT", 20), "CTFTIME_EVENT_LIMIT"
        ),
        ctftime_user_agent=env.get(
            "CTFTIME_USER_AGENT", "ctfbot/2.0 (+discord)"
        ).strip()
        or "ctfbot/2.0 (+discord)",
    )
