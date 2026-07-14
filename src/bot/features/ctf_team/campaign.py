import datetime

from bot.db import Database
from bot.errors import ServiceError
from bot.features.ctf_team.models import Campaign, CampaignDraft

MAX_ACTIVE_PER_USER = 5
MAX_CTF_NAME_LENGTH = 60
ARCHIVE_DELAY_DAYS = 30
INPUT_DATETIME_FORMAT = "%Y-%m-%d %H:%M"


def parse_datetime(raw: str, tz: datetime.tzinfo) -> datetime.datetime:
    try:
        return datetime.datetime.strptime(raw.strip(), INPUT_DATETIME_FORMAT).replace(
            tzinfo=tz
        )
    except ValueError as exc:
        raise ServiceError(
            "開始/終了日時の形式が不正です。YYYY-MM-DD HH:MM 形式で入力してください。"
        ) from exc


def to_unix(dt: datetime.datetime) -> int:
    return int(dt.timestamp())


def now_unix(tz: datetime.tzinfo) -> int:
    return int(datetime.datetime.now(tz).timestamp())


def parse_campaign_draft(
    *,
    ctf_name: str,
    start_at_raw: str,
    end_at_raw: str,
    timezone: datetime.tzinfo,
) -> CampaignDraft:
    normalized_name = " ".join(ctf_name.strip().split())
    if not normalized_name:
        raise ServiceError("CTF名を入力してください。")
    if len(normalized_name) > MAX_CTF_NAME_LENGTH:
        raise ServiceError("CTF名が長すぎます。60文字以内で入力してください。")

    start_at = parse_datetime(start_at_raw, timezone)
    end_at_unix = None
    if end_at_raw.strip():
        end_at = parse_datetime(end_at_raw, timezone)
        if end_at <= start_at:
            raise ServiceError(
                "終了日時は開始日時より後にしてください。"
                "常設CTFの場合は終了日時を空欄にしてください。"
            )
        end_at_unix = to_unix(end_at)

    return CampaignDraft(
        ctf_name=normalized_name,
        start_at_unix=to_unix(start_at),
        end_at_unix=end_at_unix,
    )


def ensure_campaign_can_be_created(
    db: Database,
    *,
    guild_id: int,
    created_by: int,
    draft: CampaignDraft,
) -> None:
    if (
        db.count_active_campaigns_by_creator(guild_id, created_by)
        >= MAX_ACTIVE_PER_USER
    ):
        raise ServiceError(
            "同時に作成できる active 募集数の上限に達しています。(上限: 5)"
        )
    if db.has_active_campaign_with_name(guild_id, draft.ctf_name):
        raise ServiceError(
            "同名の active 募集が既に存在します。"
            "別名を使うか既存募集を close してください。"
        )


def calculate_close(tz: datetime.tzinfo) -> tuple[int, int]:
    closed_at = now_unix(tz)
    archive_at = closed_at + ARCHIVE_DELAY_DAYS * 24 * 60 * 60
    return closed_at, archive_at


def is_expired(campaign: Campaign, tz: datetime.tzinfo) -> bool:
    return campaign.end_at_unix is not None and campaign.end_at_unix <= now_unix(tz)


def is_started(campaign: Campaign, tz: datetime.tzinfo) -> bool:
    return campaign.start_at_unix <= now_unix(tz)
