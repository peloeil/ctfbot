from __future__ import annotations

import asyncio
import builtins
from typing import Any

import discord

from ...errors import ConflictError, RepositoryError
from ...utils.helpers import logger, send_interaction_message, send_message_safely
from .models import CTFRoleCampaign


async def handle_create_modal_submit(
    cog: Any,
    interaction: discord.Interaction,
    *,
    ctf_name: str,
    role_color_value: int | None,
    start_at_raw: str,
    end_at_raw: str,
) -> None:
    if interaction.guild is None:
        await send_interaction_message(
            interaction,
            "このコマンドはサーバー内でのみ使用できます。",
            ephemeral=True,
        )
        return

    guild = interaction.guild

    await interaction.response.defer(ephemeral=True, thinking=True)

    validation = await asyncio.to_thread(
        cog.usecase.validate_campaign_draft,
        guild_id=guild.id,
        created_by=interaction.user.id,
        ctf_name=ctf_name,
        start_at_raw=start_at_raw,
        end_at_raw=end_at_raw,
    )
    if not validation.is_valid or validation.draft is None:
        await interaction.followup.send(validation.error_message, ephemeral=True)
        return

    draft = validation.draft
    announce_channel = cog._resolve_role_announce_channel(guild)
    if announce_channel is None:
        await interaction.followup.send(
            "`role` という名前のテキストチャンネルが見つかりません。"
            "募集メッセージの投稿先として `#role` を作成してください。",
            ephemeral=True,
        )
        return

    discussion_channel: discord.TextChannel | None = None
    voice_channel: discord.VoiceChannel | None = None
    role: discord.Role | None = None
    message: discord.Message | None = None
    campaign: CTFRoleCampaign | None = None
    create_warnings: builtins.list[str] = []

    try:
        role_color = (
            discord.Color(role_color_value)
            if role_color_value is not None
            else discord.Color.default()
        )
        role = await guild.create_role(
            name=draft.ctf_name,
            color=role_color,
            mentionable=True,
            reason=f"CTF role campaign created by {interaction.user.id}",
        )
        creator_member = (
            interaction.user if isinstance(interaction.user, discord.Member) else None
        )
        discussion_channel = await cog._create_ctf_discussion_channel(
            guild=guild,
            draft=draft,
            role=role,
            creator=creator_member,
            creator_id=interaction.user.id,
        )
        voice_channel = await cog._create_ctf_voice_channel(
            guild=guild,
            draft=draft,
            role=role,
            creator=creator_member,
            creator_id=interaction.user.id,
        )
        content = cog._build_recruitment_message(
            draft=draft,
            role=role,
            discussion_channel=discussion_channel,
        )
        message = await send_message_safely(announce_channel, content=content)
        if message is None:
            raise RuntimeError("Failed to send recruitment message.")
        await message.add_reaction(cog.REACTION_EMOJI)

        campaign = await asyncio.to_thread(
            cog.usecase.create_campaign,
            guild_id=guild.id,
            channel_id=announce_channel.id,
            message_id=message.id,
            role_id=role.id,
            discussion_channel_id=discussion_channel.id,
            voice_channel_id=voice_channel.id if voice_channel is not None else None,
            created_by=interaction.user.id,
            draft=draft,
        )
        if cog.usecase.is_campaign_started(campaign):
            started, warnings = await cog._start_campaign(campaign)
            if not started:
                create_warnings.extend(warnings)
    except ConflictError:
        await cog._cleanup_created_resources(
            discussion_channel=discussion_channel,
            voice_channel=voice_channel,
            role=role,
            message=message,
        )
        await interaction.followup.send(
            "同名の active 募集が既に存在するため作成できませんでした。"
            "別名を使うか既存募集を close してください。",
            ephemeral=True,
        )
        return
    except RepositoryError:
        await cog._cleanup_created_resources(
            discussion_channel=discussion_channel,
            voice_channel=voice_channel,
            role=role,
            message=message,
        )
        logger.exception("Repository error while creating CTF role campaign")
        await interaction.followup.send(
            "募集の保存中にエラーが発生しました。",
            ephemeral=True,
        )
        return
    except discord.Forbidden:
        await cog._cleanup_created_resources(
            discussion_channel=discussion_channel,
            voice_channel=voice_channel,
            role=role,
            message=message,
        )
        await interaction.followup.send(
            "Botの権限不足で募集作成に失敗しました。"
            "Manage Roles / Manage Channels / Add Reactions "
            "権限を確認してください。",
            ephemeral=True,
        )
        return
    except discord.HTTPException:
        logger.exception("Discord API error while creating CTF role campaign")
        await cog._cleanup_created_resources(
            discussion_channel=discussion_channel,
            voice_channel=voice_channel,
            role=role,
            message=message,
        )
        await interaction.followup.send(
            "募集作成中に Discord API エラーが発生しました。",
            ephemeral=True,
        )
        return
    except Exception:
        logger.exception("Unexpected error while creating CTF role campaign")
        await cog._cleanup_created_resources(
            discussion_channel=discussion_channel,
            voice_channel=voice_channel,
            role=role,
            message=message,
        )
        await interaction.followup.send(
            "募集作成中にエラーが発生しました。",
            ephemeral=True,
        )
        return

    assert message is not None
    assert discussion_channel is not None
    assert voice_channel is not None
    summary = (
        "募集を作成しました: "
        f"{message.jump_url}\n"
        f"募集投稿先: {announce_channel.mention}\n"
        f"CTFチャンネル: {discussion_channel.mention}\n"
        f"Voiceチャンネル: {voice_channel.mention}"
    )
    if create_warnings:
        summary += (
            "\nただし開始通知の後処理に失敗しました: " + ", ".join(create_warnings)
        )
    await interaction.followup.send(summary, ephemeral=True)
