from dataclasses import dataclass
from enum import Enum


class CampaignStatus(Enum):
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class Campaign:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    role_id: int
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
    status: CampaignStatus
    created_by: int
    created_at_unix: int
    start_notified_at_unix: int | None = None
    closed_at_unix: int | None = None
    archive_at_unix: int | None = None
    archived_at_unix: int | None = None
    discussion_channel_id: int | None = None
    voice_channel_id: int | None = None


@dataclass(frozen=True, slots=True)
class CampaignDraft:
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
