import re

import discord
from discord.ext import commands

from bot.features.ctf_team.models import CampaignDraft
from bot.helpers import format_timestamp_with_relative, send_safely
from bot.log import logger

MAX_CHANNEL_NAME_LENGTH = 100
CLOSED_HEADER = "🔒 **この募集は終了しました。**"
MENTION_CHUNK_SIZE = 1700
type OverwriteMap = dict[
    discord.Role | discord.Member | discord.Object, discord.PermissionOverwrite
]


def normalize_channel_name(ctf_name: str) -> str:
    value = ctf_name.lower().replace(" ", "-")
    value = re.sub(r"[^a-z0-9\-]", "", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return (value or "ctf")[:MAX_CHANNEL_NAME_LENGTH]


def pick_unique_channel_name(category: discord.CategoryChannel, base: str) -> str:
    existing = {channel.name for channel in category.channels}
    candidate = base[:MAX_CHANNEL_NAME_LENGTH]
    if candidate not in existing:
        return candidate
    suffix = 2
    while True:
        tail = f"-{suffix}"
        candidate = f"{base[: MAX_CHANNEL_NAME_LENGTH - len(tail)]}{tail}"
        if candidate not in existing:
            return candidate
        suffix += 1


def _text_overwrites(
    guild: discord.Guild,
    role: discord.Role,
    creator: discord.Member | None,
    bot_member: discord.Member | None,
) -> OverwriteMap:
    overwrites: OverwriteMap = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
    }
    if creator is not None:
        overwrites[creator] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )
    if bot_member is not None:
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
        )
    return overwrites


def _voice_overwrites(
    guild: discord.Guild,
    role: discord.Role,
    creator: discord.Member | None,
    bot_member: discord.Member | None,
) -> OverwriteMap:
    overwrites: OverwriteMap = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        role: discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
        ),
    }
    if creator is not None:
        overwrites[creator] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
        )
    if bot_member is not None:
        overwrites[bot_member] = discord.PermissionOverwrite(
            view_channel=True,
            connect=True,
            speak=True,
            stream=True,
        )
    return overwrites


async def create_discussion_channel(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    ctf_name: str,
    role: discord.Role,
    creator: discord.Member | None,
    bot_member: discord.Member | None,
) -> discord.TextChannel:
    base = normalize_channel_name(ctf_name)
    name = pick_unique_channel_name(category, base)
    return await guild.create_text_channel(
        name=name,
        category=category,
        overwrites=_text_overwrites(guild, role, creator, bot_member),
    )


async def create_voice_channel(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    ctf_name: str,
    role: discord.Role,
    creator: discord.Member | None,
    bot_member: discord.Member | None,
) -> discord.VoiceChannel:
    base = normalize_channel_name(ctf_name)
    name = pick_unique_channel_name(category, f"{base}-voice")
    return await guild.create_voice_channel(
        name=name,
        category=category,
        overwrites=_voice_overwrites(guild, role, creator, bot_member),
    )


async def archive_discussion_channel(
    discussion: discord.TextChannel,
    archive_category: discord.CategoryChannel,
    role: discord.Role | None,
    bot_member: discord.Member | None,
) -> bool:
    try:
        if bot_member is not None:
            overwrite = discussion.overwrites_for(bot_member)
            overwrite.manage_channels = True
            await discussion.set_permissions(bot_member, overwrite=overwrite)
        await discussion.edit(category=archive_category)
        await discussion.set_permissions(
            discussion.guild.default_role,
            view_channel=True,
            send_messages=False,
            add_reactions=False,
            create_public_threads=False,
            create_private_threads=False,
            read_message_history=True,
        )
        if role is not None:
            await discussion.set_permissions(role, overwrite=None)
        await send_safely(
            discussion, "📦 このチャンネルは archive カテゴリに移動されました。"
        )
        return True
    except discord.NotFound:
        return True
    except discord.Forbidden:
        logger.warning("Forbidden while archiving discussion channel %s", discussion.id)
        return False
    except discord.HTTPException:
        logger.exception("Failed to archive discussion channel %s", discussion.id)
        return False


async def delete_voice_channel(
    bot: commands.Bot,
    guild: discord.Guild,
    channel_id: int | None,
) -> bool:
    if not channel_id:
        return True
    channel = guild.get_channel(channel_id)
    if channel is None:
        try:
            fetched = await bot.fetch_channel(channel_id)
        except discord.NotFound:
            return True
        except discord.Forbidden, discord.HTTPException:
            logger.warning("Failed to fetch voice channel %s", channel_id)
            return False
        channel = fetched if isinstance(fetched, discord.VoiceChannel) else None
    if channel is None:
        return True
    try:
        await channel.delete()
        return True
    except discord.NotFound:
        return True
    except discord.Forbidden, discord.HTTPException:
        logger.warning("Failed to delete voice channel %s", channel_id)
        return False


async def cleanup_resources(
    *,
    message: discord.Message | None = None,
    role: discord.Role | None = None,
    discussion: discord.TextChannel | None = None,
    voice: discord.VoiceChannel | None = None,
) -> None:
    for resource in (message, voice, discussion, role):
        if resource is None:
            continue
        try:
            await resource.delete()
        except discord.NotFound, discord.Forbidden, discord.HTTPException:
            logger.warning("Failed to cleanup resource %s", resource)


async def mark_message_closed(
    channel: discord.TextChannel,
    message_id: int,
) -> bool:
    try:
        message = await channel.fetch_message(message_id)
        if message.content.startswith(CLOSED_HEADER):
            return True
        await message.edit(content=f"{CLOSED_HEADER}\n\n{message.content}")
        return True
    except discord.NotFound:
        return True
    except discord.Forbidden, discord.HTTPException:
        logger.warning("Failed to mark recruitment message %s closed", message_id)
        return False


def _chunk_mentions(mentions: list[str]) -> list[str]:
    chunks: list[str] = []
    current = ""
    for mention in mentions:
        next_value = mention if not current else f"{current} {mention}"
        if len(next_value) > MENTION_CHUNK_SIZE:
            if current:
                chunks.append(current)
            current = mention
        else:
            current = next_value
    if current:
        chunks.append(current)
    return chunks


async def send_start_announcement(
    channel: discord.TextChannel,
    campaign_name: str,
    role: discord.Role,
) -> tuple[int, bool]:
    members = list(role.members)
    sent = await send_safely(channel, f"🚀 **{campaign_name}** が開始しました!")
    success = sent is not None
    for chunk in _chunk_mentions([member.mention for member in members]):
        success = (await send_safely(channel, chunk)) is not None and success
    return len(members), success


async def send_close_snapshot(
    channel: discord.TextChannel,
    campaign_name: str,
    role: discord.Role,
) -> tuple[int, bool]:
    members = list(role.members)
    header = f"🔒 **{campaign_name}** の募集が終了しました。"
    lines = [header, f"参加メンバー ({len(members)}人):"]
    chunks = _chunk_mentions([member.mention for member in members])
    success = (await send_safely(channel, "\n".join(lines))) is not None
    for chunk in chunks:
        success = (await send_safely(channel, chunk)) is not None and success
    return len(members), success


async def send_join_announcement(
    channel: discord.TextChannel,
    member: discord.Member,
    campaign_name: str,
) -> None:
    await send_safely(
        channel, f"🙋 {member.mention} が **{campaign_name}** に参加しました。"
    )


def build_recruitment_message(
    draft: CampaignDraft,
    role: discord.Role,
    discussion_channel: discord.TextChannel,
) -> str:
    end_text = (
        "常設"
        if draft.end_at_unix is None
        else format_timestamp_with_relative(draft.end_at_unix)
    )
    return (
        f"📣 **{draft.ctf_name}** 参加者募集\n\n"
        f"🕐 開始: {format_timestamp_with_relative(draft.start_at_unix)}\n"
        f"🏁 終了: {end_text}\n"
        f"💬 CTFチャンネル: {discussion_channel.mention}\n"
        f"👥 ロール: {role.mention}\n\n"
        f"✅ リアクションを付けると {role.mention} ロールを付与します。"
    )
