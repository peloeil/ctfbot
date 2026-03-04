from __future__ import annotations

from .models import (
    CampaignCloseResult,
    CampaignDraft,
    CampaignDraftValidation,
    CampaignStatus,
    CTFRoleCampaign,
)
from .repository import CTFRoleCampaignRepository
from .service import CTFRoleService

DEFAULT_MAX_ACTIVE_CAMPAIGNS_PER_USER = 3
DEFAULT_MAX_CTF_NAME_LENGTH = 60
DEFAULT_ARCHIVE_DELAY_DAYS = 30


class CTFRoleUseCase:
    def __init__(
        self,
        repository: CTFRoleCampaignRepository,
        service: CTFRoleService,
        *,
        max_active_campaigns_per_user: int = DEFAULT_MAX_ACTIVE_CAMPAIGNS_PER_USER,
        max_ctf_name_length: int = DEFAULT_MAX_CTF_NAME_LENGTH,
        archive_delay_days: int = DEFAULT_ARCHIVE_DELAY_DAYS,
    ) -> None:
        self._repository = repository
        self._service = service
        self._max_active_campaigns_per_user = max(1, max_active_campaigns_per_user)
        self._max_ctf_name_length = max(8, max_ctf_name_length)
        self._archive_delay_seconds = max(1, archive_delay_days) * 24 * 60 * 60

    def validate_campaign_draft(
        self,
        *,
        guild_id: int,
        created_by: int,
        ctf_name: str,
        start_at_raw: str,
        end_at_raw: str,
    ) -> CampaignDraftValidation:
        normalized_name = " ".join(ctf_name.strip().split())
        if not normalized_name:
            return CampaignDraftValidation(
                is_valid=False,
                error_message="CTF名を入力してください。",
            )
        if len(normalized_name) > self._max_ctf_name_length:
            return CampaignDraftValidation(
                is_valid=False,
                error_message=(
                    "CTF名が長すぎます。"
                    f"{self._max_ctf_name_length}文字以内で入力してください。"
                ),
            )

        try:
            start_at = self._service.parse_local_datetime(start_at_raw)
        except Exception:
            return CampaignDraftValidation(
                is_valid=False,
                error_message=(
                    "開始日時の形式が不正です。"
                    "YYYY-MM-DD HH:MM 形式で入力してください。"
                ),
            )

        end_at_unix: int | None = None
        normalized_end = end_at_raw.strip()
        if normalized_end:
            try:
                end_at = self._service.parse_local_datetime(normalized_end)
            except Exception:
                return CampaignDraftValidation(
                    is_valid=False,
                    error_message=(
                        "終了日時の形式が不正です。"
                        "YYYY-MM-DD HH:MM 形式で入力してください。"
                    ),
                )
            if end_at <= start_at:
                return CampaignDraftValidation(
                    is_valid=False,
                    error_message=(
                        "終了日時は開始日時より後にしてください。"
                        "常設CTFの場合は終了日時を空欄にしてください。"
                    ),
                )
            end_at_unix = self._service.to_unix(end_at)

        current_active = self._repository.count_active_campaigns_by_creator(
            guild_id=guild_id,
            created_by=created_by,
        )
        if current_active >= self._max_active_campaigns_per_user:
            return CampaignDraftValidation(
                is_valid=False,
                error_message=(
                    "同時に作成できる active 募集数の上限に達しています。"
                    f"(上限: {self._max_active_campaigns_per_user})"
                ),
            )

        if self._repository.has_active_campaign_with_name(guild_id, normalized_name):
            return CampaignDraftValidation(
                is_valid=False,
                error_message=(
                    "同名の active 募集が既に存在します。"
                    "別名を使うか既存募集を close してください。"
                ),
            )

        draft = CampaignDraft(
            ctf_name=normalized_name,
            start_at_unix=self._service.to_unix(start_at),
            end_at_unix=end_at_unix,
        )
        return CampaignDraftValidation(is_valid=True, draft=draft)

    def create_campaign(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
        role_id: int,
        discussion_channel_id: int | None,
        created_by: int,
        draft: CampaignDraft,
    ) -> CTFRoleCampaign:
        return self._repository.create_campaign(
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            role_id=role_id,
            discussion_channel_id=discussion_channel_id,
            ctf_name=draft.ctf_name,
            start_at_unix=draft.start_at_unix,
            end_at_unix=draft.end_at_unix,
            created_by=created_by,
            created_at_unix=self._service.now_unix(),
        )

    def find_active_campaign_by_message(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> CTFRoleCampaign | None:
        return self._repository.find_active_campaign_by_message(
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
        )

    def find_active_campaign_by_name(
        self, *, guild_id: int, ctf_name: str
    ) -> CTFRoleCampaign | None:
        return self._repository.find_active_campaign_by_name(
            guild_id=guild_id,
            ctf_name=ctf_name.strip(),
        )

    def list_due_campaigns(self, *, limit: int = 20) -> list[CTFRoleCampaign]:
        return self._repository.list_due_campaigns(
            now_unix=self._service.now_unix(),
            limit=limit,
        )

    def close_campaign(self, *, campaign_id: int) -> CampaignCloseResult:
        closed_at_unix = self._service.now_unix()
        archive_at_unix = closed_at_unix + self._archive_delay_seconds
        closed = self._repository.close_campaign(
            campaign_id=campaign_id,
            closed_at_unix=closed_at_unix,
            archive_at_unix=archive_at_unix,
        )
        if not closed:
            return CampaignCloseResult(was_closed=False)
        return CampaignCloseResult(
            was_closed=True,
            closed_at_unix=closed_at_unix,
            archive_at_unix=archive_at_unix,
        )

    def is_campaign_expired(self, campaign: CTFRoleCampaign) -> bool:
        if campaign.end_at_unix is None:
            return False
        return campaign.end_at_unix <= self._service.now_unix()

    def list_due_archives(self, *, limit: int = 20) -> list[CTFRoleCampaign]:
        return self._repository.list_due_archives(
            now_unix=self._service.now_unix(),
            limit=limit,
        )

    def mark_campaign_archived(self, *, campaign_id: int) -> bool:
        return self._repository.mark_campaign_archived(
            campaign_id=campaign_id,
            archived_at_unix=self._service.now_unix(),
        )

    def list_campaigns(
        self,
        *,
        guild_id: int,
        status: str,
        limit: int = 20,
    ) -> list[CTFRoleCampaign]:
        if status == CampaignStatus.ACTIVE.value:
            filter_status = CampaignStatus.ACTIVE
        elif status == CampaignStatus.CLOSED.value:
            filter_status = CampaignStatus.CLOSED
        else:
            filter_status = None
        return self._repository.list_campaigns(
            guild_id=guild_id,
            status=filter_status,
            limit=limit,
        )

    def format_unix_datetime(self, value: int | None) -> str:
        return self._service.format_unix(value)
