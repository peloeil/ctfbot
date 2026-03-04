from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CampaignStatus(Enum):
    ACTIVE = "active"
    CLOSED = "closed"


INPUT_DATETIME_PLACEHOLDER = "YYYY-MM-DD HH:MM"


@dataclass(frozen=True, slots=True)
class CTFRoleCampaign:
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
    closed_at_unix: int | None


@dataclass(frozen=True, slots=True)
class CampaignDraft:
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None


@dataclass(frozen=True, slots=True)
class CampaignDraftValidation:
    is_valid: bool
    error_message: str = ""
    draft: CampaignDraft | None = None
