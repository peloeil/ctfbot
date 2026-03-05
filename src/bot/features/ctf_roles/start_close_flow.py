from __future__ import annotations

import asyncio
from typing import Any

from .models import CloseCampaignReport, CTFRoleCampaign


async def close_campaign(
    cog: Any,
    campaign: CTFRoleCampaign,
) -> CloseCampaignReport:
    close_result = await asyncio.to_thread(
        cog.usecase.close_campaign,
        campaign_id=campaign.id,
    )
    if not close_result.was_closed:
        return CloseCampaignReport(was_closed=False)

    warnings: list[str] = []
    guild = cog.bot.get_guild(campaign.guild_id)
    if guild is None:
        warnings.append("guild_not_found")
        return CloseCampaignReport(
            was_closed=True,
            archive_at_unix=close_result.archive_at_unix,
            warnings=tuple(warnings),
        )

    role = await cog._resolve_role(guild, campaign.role_id)
    snapshot_count, snapshot_saved = await cog._record_members_on_close(
        guild=guild,
        campaign=campaign,
        role=role,
        archive_at_unix=close_result.archive_at_unix,
    )
    if not snapshot_saved:
        warnings.append("member_snapshot_failed")

    message_closed = await cog._mark_campaign_message_closed(
        guild,
        campaign,
        archive_at_unix=close_result.archive_at_unix,
    )
    if not message_closed:
        warnings.append("message_update_failed")

    voice_deleted = await cog._delete_voice_channel(
        guild=guild,
        campaign=campaign,
        reason="CTF campaign closed",
    )
    if not voice_deleted:
        warnings.append("voice_delete_failed")

    return CloseCampaignReport(
        was_closed=True,
        archive_at_unix=close_result.archive_at_unix,
        snapshot_member_count=snapshot_count,
        warnings=tuple(warnings),
    )


async def start_campaign(
    cog: Any,
    campaign: CTFRoleCampaign,
) -> tuple[bool, tuple[str, ...]]:
    warnings: list[str] = []

    guild = cog.bot.get_guild(campaign.guild_id)
    if guild is None:
        warnings.append("guild_not_found")
        marked = await asyncio.to_thread(
            cog.usecase.mark_campaign_started,
            campaign_id=campaign.id,
        )
        if not marked:
            warnings.append("start_state_update_failed")
        return False, tuple(warnings)

    role = await cog._resolve_role(guild, campaign.role_id)
    if role is None:
        warnings.append("role_not_found")
        marked = await asyncio.to_thread(
            cog.usecase.mark_campaign_started,
            campaign_id=campaign.id,
        )
        if not marked:
            warnings.append("start_state_update_failed")
        return False, tuple(warnings)

    _member_count, announced = await cog._send_start_announcement(
        guild=guild,
        campaign=campaign,
        role=role,
    )
    if not announced:
        warnings.append("start_announce_failed")
        marked = await asyncio.to_thread(
            cog.usecase.mark_campaign_started,
            campaign_id=campaign.id,
        )
        if not marked:
            warnings.append("start_state_update_failed")
        return False, tuple(warnings)

    marked = await asyncio.to_thread(
        cog.usecase.mark_campaign_started,
        campaign_id=campaign.id,
    )
    if not marked:
        warnings.append("start_state_update_failed")
        return False, tuple(warnings)

    return True, ()
