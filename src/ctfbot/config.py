import datetime
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ctfbot.errors import ConfigurationError


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    guild_id: int
    bot_channel_id: int | None
    ctfteam_category_id: int | None
    ctfteam_archive_category_id: int | None
    ctfteam_role_channel_id: int | None
    ctftime_channel_id: int | None
    alpacahack_channel_id: int | None
    alpacahack_mention_id: int | None
    times_category_id: int | None
    admin_role_id: int | None
    sudoer_role_id: int | None
    sudo_duration_minutes: int
    tzinfo: ZoneInfo
    log_level: str
    database_path: str
    alpacahack_daily_time: datetime.time
    alpacahack_solve_time: datetime.time
    ctftime_notification_time: datetime.time
    ctftime_window_days: int
    ctftime_event_limit: int
    ctftime_user_agent: str
    tts_voicevox_url: str | None
    tts_speaker_ids: tuple[int, ...]
    tts_max_chars: int
    tts_speed_scale: float

    @property
    def tts_enabled(self) -> bool:
        return self.tts_voicevox_url is not None


MAX_TTS_CHARS = 1000
DEFAULT_TTS_SPEAKER_IDS = (3, 2, 8, 11, 14, 13)
DEFAULT_TTS_SPEED_SCALE = 2.0
MIN_TTS_SPEED_SCALE = 0.5
MAX_TTS_SPEED_SCALE = 2.0


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


def _read_int_list(
    environ: Mapping[str, str], name: str, default: tuple[int, ...]
) -> tuple[int, ...]:
    raw = environ.get(name, "").strip()
    if not raw:
        return default
    values: dict[int, None] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            raise ConfigurationError(f"{name} must not contain empty items.")
        try:
            value = int(item)
        except ValueError as exc:
            raise ConfigurationError(
                f"{name} must be comma-separated integers."
            ) from exc
        if value < 0:
            raise ConfigurationError(f"{name} must be non-negative.")
        values.setdefault(value)
    return tuple(values)


def _read_tts_speed_scale(environ: Mapping[str, str]) -> float:
    raw = environ.get("TTS_SPEED_SCALE", "").strip()
    if not raw:
        return DEFAULT_TTS_SPEED_SCALE
    message = (
        f"TTS_SPEED_SCALE must be a number between "
        f"{MIN_TTS_SPEED_SCALE} and {MAX_TTS_SPEED_SCALE}."
    )
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(message) from exc
    # nan passes every range comparison it appears in, so reject it explicitly
    if not math.isfinite(value) or not (
        MIN_TTS_SPEED_SCALE <= value <= MAX_TTS_SPEED_SCALE
    ):
        raise ConfigurationError(message)
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
    environ: Mapping[str, str] | None = None,
) -> Settings:
    env = os.environ if environ is None else environ

    discord_token = env.get("DISCORD_TOKEN", "").strip()
    if not discord_token:
        raise ConfigurationError("DISCORD_TOKEN is required.")

    guild_id = _read_int(env, "GUILD_ID")
    if guild_id <= 0:
        raise ConfigurationError("GUILD_ID must be greater than 0.")

    timezone = env.get("TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo"
    try:
        tzinfo = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigurationError(f"Unknown TIMEZONE: {timezone}") from exc

    ctfteam_category_id = _read_int(env, "CTFTEAM_CATEGORY_ID", 0) or None
    ctfteam_archive_category_id = (
        _read_int(env, "CTFTEAM_ARCHIVE_CATEGORY_ID", 0) or None
    )
    ctfteam_role_channel_id = _read_int(env, "CTFTEAM_ROLE_CHANNEL_ID", 0) or None
    ctfteam_ids = (
        ctfteam_category_id,
        ctfteam_archive_category_id,
        ctfteam_role_channel_id,
    )
    if any(value is None for value in ctfteam_ids) and any(
        value is not None for value in ctfteam_ids
    ):
        raise ConfigurationError(
            "CTFTEAM_CATEGORY_ID, CTFTEAM_ARCHIVE_CATEGORY_ID, and "
            "CTFTEAM_ROLE_CHANNEL_ID must all be set or all be unset."
        )

    database_path = env.get("DATABASE_PATH", "ctfbot.db").strip() or "ctfbot.db"
    parent = Path(database_path).expanduser().resolve().parent
    if not parent.exists():
        raise ConfigurationError(f"DATABASE_PATH parent does not exist: {parent}")

    admin_role_id = _read_int(env, "ADMIN_ROLE_ID", 0) or None
    sudoer_role_id = _read_int(env, "SUDOER_ROLE_ID", 0) or None
    if (admin_role_id is None) != (sudoer_role_id is None):
        raise ConfigurationError(
            "ADMIN_ROLE_ID and SUDOER_ROLE_ID must both be set or both be unset."
        )
    if admin_role_id is not None and admin_role_id == sudoer_role_id:
        raise ConfigurationError(
            "ADMIN_ROLE_ID and SUDOER_ROLE_ID must be different roles."
        )

    tts_max_chars = _require_positive(
        _read_int(env, "TTS_MAX_CHARS", 200), "TTS_MAX_CHARS"
    )
    if tts_max_chars > MAX_TTS_CHARS:
        raise ConfigurationError(f"TTS_MAX_CHARS must be at most {MAX_TTS_CHARS}.")

    return Settings(
        discord_token=discord_token,
        guild_id=guild_id,
        bot_channel_id=_read_int(env, "BOT_CHANNEL_ID", 0) or None,
        ctfteam_category_id=ctfteam_category_id,
        ctfteam_archive_category_id=ctfteam_archive_category_id,
        ctfteam_role_channel_id=ctfteam_role_channel_id,
        ctftime_channel_id=_read_int(env, "CTFTIME_CHANNEL_ID", 0) or None,
        alpacahack_channel_id=_read_int(env, "ALPACAHACK_CHANNEL_ID", 0) or None,
        alpacahack_mention_id=_read_int(env, "ALPACAHACK_MENTION_ID", 0) or None,
        times_category_id=_read_int(env, "TIMES_CATEGORY_ID", 0) or None,
        admin_role_id=admin_role_id,
        sudoer_role_id=sudoer_role_id,
        sudo_duration_minutes=_require_positive(
            _read_int(env, "SUDO_DURATION_MINUTES", 30), "SUDO_DURATION_MINUTES"
        ),
        tzinfo=tzinfo,
        log_level=env.get("LOG_LEVEL", "INFO").strip() or "INFO",
        database_path=database_path,
        alpacahack_daily_time=_read_clock_time(
            env, "ALPACAHACK_DAILY_TIME", "00:05", tzinfo=tzinfo
        ),
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
        tts_voicevox_url=env.get("TTS_VOICEVOX_URL", "").strip() or None,
        tts_speaker_ids=_read_int_list(env, "TTS_SPEAKER_IDS", DEFAULT_TTS_SPEAKER_IDS),
        tts_max_chars=tts_max_chars,
        tts_speed_scale=_read_tts_speed_scale(env),
    )
