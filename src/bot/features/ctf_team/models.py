from dataclasses import dataclass
from enum import Enum
from typing import Literal


class CampaignStatus(Enum):
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class ActiveCampaign:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    role_id: int
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
    status: Literal[CampaignStatus.ACTIVE]
    created_by: int
    created_at_unix: int
    start_notified_at_unix: int | None = None
    discussion_channel_id: int | None = None
    voice_channel_id: int | None = None


@dataclass(frozen=True, slots=True)
class ClosedCampaign:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    role_id: int
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
    status: Literal[CampaignStatus.CLOSED]
    created_by: int
    created_at_unix: int
    closed_at_unix: int
    archive_at_unix: int
    archived_at_unix: int | None = None
    discussion_channel_id: int | None = None
    voice_channel_id: int | None = None


type Campaign = ActiveCampaign | ClosedCampaign


@dataclass(frozen=True, slots=True)
class CampaignDraft:
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
