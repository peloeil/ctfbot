from __future__ import annotations

import asyncio
from typing import Any

import discord

from ...log import logger
from .models import CTFTeamCampaign


async def archive_campaign(
    cog: Any,
    campaign: CTFTeamCampaign,
    *,
    reason: str,
) -> tuple[bool, tuple[str, ...]]:
    warnings: list[str] = []

    guild = cog.bot.get_guild(campaign.guild_id)
    if guild is None:
        return False, ("guild_not_found",)

    role = await cog._resolve_role(guild, campaign.role_id)
    archived = await cog._archive_discussion_channel(
        guild=guild,
        campaign=campaign,
        role=role,
        reason=reason,
    )
    if not archived:
        warnings.append("discussion_archive_failed")
        return False, tuple(warnings)

    voice_deleted = await cog._delete_voice_channel(
        guild=guild,
        campaign=campaign,
        reason=reason,
    )
    if not voice_deleted:
        warnings.append("voice_delete_failed")
        return False, tuple(warnings)

    if role is not None:
        try:
            await role.delete(reason=reason)
        except discord.Forbidden, discord.HTTPException:
            logger.warning("Failed to delete role for archive: %s", campaign.id)
            return False, ("role_delete_failed",)

    marked = await asyncio.to_thread(
        cog.usecase.mark_campaign_archived,
        campaign_id=campaign.id,
    )
    if not marked:
        return False, ("archive_state_update_failed",)

    return True, ()
