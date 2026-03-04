from __future__ import annotations

import asyncio
import builtins
import re
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ...cogs._runtime import get_runtime
from ...utils.helpers import logger, send_interaction_message, send_message_safely
from .models import INPUT_DATETIME_PLACEHOLDER, CampaignDraft, CTFRoleCampaign

REACTION_EMOJI = "✅"
LIST_LIMIT = 20
STATUS_ACTIVE = "active"
STATUS_CLOSED = "closed"
STATUS_ALL = "all"
CLOSED_HEADER = "🔒 **この募集は終了しました。**"
CTF_CATEGORY_NAME = "ctf"
ARCHIVE_CATEGORY_NAME = "archive"
ROLE_ANNOUNCE_CHANNEL_NAME = "role"
FALLBACK_CHANNEL_NAME = "ctf"
MAX_CHANNEL_NAME_LENGTH = 100
ROLE_COLOR_SUGGESTIONS: tuple[tuple[str, str], ...] = (
    ("🟥 Red", "#ef4444"),
    ("🟧 Orange", "#f97316"),
    ("🟨 Yellow", "#eab308"),
    ("🟩 Green", "#22c55e"),
    ("🟦 Blue", "#3b82f6"),
    ("🟪 Purple", "#a855f7"),
    ("🟫 Brown", "#92400e"),
    ("⬜ White", "#f3f4f6"),
    ("⬛ Gray", "#6b7280"),
)


@dataclass(frozen=True, slots=True)
class CloseCampaignReport:
    was_closed: bool
    warnings: tuple[str, ...] = ()


class CTFRoleCreateModal(discord.ui.Modal, title="CTF Role 募集作成"):
    def __init__(
        self,
        cog: CTFRoleCampaigns,
        *,
        ctf_name: str,
        role_color_value: int | None,
    ) -> None:
        super().__init__()
        self._cog = cog
        self._ctf_name = ctf_name
        self._role_color_value = role_color_value
        timezone_label = cog.timezone_label
        self.start_at_input = discord.ui.TextInput(
            label=f"開始日時 ({timezone_label})",
            placeholder=INPUT_DATETIME_PLACEHOLDER,
            required=True,
            max_length=16,
        )
        self.end_at_input = discord.ui.TextInput(
            label=f"終了日時 ({timezone_label}, 任意)",
            placeholder=INPUT_DATETIME_PLACEHOLDER,
            required=False,
            max_length=16,
        )
        self.add_item(self.start_at_input)
        self.add_item(self.end_at_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._cog.handle_create_modal_submit(
            interaction,
            ctf_name=self._ctf_name,
            role_color_value=self._role_color_value,
            start_at_raw=self.start_at_input.value,
            end_at_raw=self.end_at_input.value,
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
    ) -> None:
        logger.exception("Unhandled error on CTFRoleCreateModal", exc_info=error)
        await send_interaction_message(
            interaction,
            "募集作成フォームの処理中にエラーが発生しました。",
            ephemeral=True,
        )


class CTFRoleCampaigns(
    commands.GroupCog,
    group_name="ctf-role",
    group_description="CTF参加ロール募集を管理します。",
):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = get_runtime(bot)
        self.settings = self.runtime.settings
        self.usecase = self.runtime.ctf_role_usecase
        self.timezone_label = getattr(
            self.settings.tzinfo, "key", self.settings.timezone
        )
        self.close_expired_campaigns.start()

    async def cog_unload(self) -> None:
        self.close_expired_campaigns.cancel()

    @staticmethod
    def _can_operate_in_channel(
        user: discord.abc.User, channel: discord.abc.GuildChannel
    ) -> bool:
        if not isinstance(user, discord.Member):
            return False
        if not isinstance(channel, discord.TextChannel):
            return False
        permissions = channel.permissions_for(user)
        return permissions.view_channel and permissions.send_messages

    @staticmethod
    def _can_close_campaign(
        user: discord.abc.User, campaign: CTFRoleCampaign
    ) -> bool:
        if user.id == campaign.created_by:
            return True
        if not isinstance(user, discord.Member):
            return False
        return user.guild_permissions.manage_guild

    async def _resolve_text_channel(
        self, guild: discord.Guild, channel_id: int
    ) -> discord.TextChannel | None:
        cached = guild.get_channel(channel_id)
        if isinstance(cached, discord.TextChannel):
            return cached

        try:
            fetched = await self.bot.fetch_channel(channel_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return None

        if isinstance(fetched, discord.TextChannel):
            return fetched
        return None

    async def _resolve_role(
        self, guild: discord.Guild, role_id: int
    ) -> discord.Role | None:
        cached = guild.get_role(role_id)
        if cached is not None:
            return cached

        try:
            roles = await guild.fetch_roles()
        except (discord.Forbidden, discord.HTTPException):
            return None

        for role in roles:
            if role.id == role_id:
                return role
        return None

    async def _fetch_member(
        self, guild: discord.Guild, user_id: int
    ) -> discord.Member | None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    @staticmethod
    def _build_channel_base_name(ctf_name: str) -> str:
        lowered = ctf_name.strip().lower()
        lowered = lowered.replace("_", "-")
        lowered = re.sub(r"\s+", "-", lowered)
        lowered = re.sub(r"[^\w-]", "-", lowered)
        lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
        if not lowered:
            return FALLBACK_CHANNEL_NAME
        return lowered[:MAX_CHANNEL_NAME_LENGTH].strip("-") or FALLBACK_CHANNEL_NAME

    @staticmethod
    def _build_channel_name_with_suffix(base_name: str, suffix: int) -> str:
        suffix_text = f"-{suffix}"
        max_base_length = MAX_CHANNEL_NAME_LENGTH - len(suffix_text)
        trimmed = base_name[:max_base_length].strip("-")
        if not trimmed:
            trimmed = FALLBACK_CHANNEL_NAME
        return f"{trimmed}{suffix_text}"

    @staticmethod
    def _build_discussion_channel_overwrites(
        *,
        default_role: discord.Role | discord.Object,
        role: discord.Role | discord.Object,
        creator: discord.Member | discord.Object | None,
        bot_member: discord.Member | discord.Object | None,
    ) -> dict[
        discord.Role | discord.Member | discord.Object,
        discord.PermissionOverwrite,
    ]:
        overwrites: dict[
            discord.Role | discord.Member | discord.Object,
            discord.PermissionOverwrite,
        ] = {
            default_role: discord.PermissionOverwrite(view_channel=False),
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
            # Keep bot access explicitly so it can archive and notify on close.
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
            )
        return overwrites

    def _resolve_bot_member(self, guild: discord.Guild) -> discord.Member | None:
        if guild.me is not None:
            return guild.me
        bot_user = self.bot.user
        if bot_user is None:
            return None
        member = guild.get_member(bot_user.id)
        return member if isinstance(member, discord.Member) else None

    @staticmethod
    def _normalize_role_color_token(raw_value: str) -> str:
        normalized = raw_value.strip().lower()
        if normalized.startswith("0x"):
            normalized = normalized[2:]
        if normalized.startswith("#"):
            normalized = normalized[1:]
        return normalized

    @classmethod
    def _build_role_color_suggestions(
        cls, current: str
    ) -> builtins.list[app_commands.Choice[str]]:
        query = current.strip().lower()
        normalized_query = cls._normalize_role_color_token(current)
        suggestions: builtins.list[app_commands.Choice[str]] = []

        for label, value in ROLE_COLOR_SUGGESTIONS:
            if query:
                lowered_label = label.lower()
                if (
                    query not in lowered_label
                    and query not in value
                    and normalized_query not in value[1:]
                ):
                    continue
            suggestions.append(
                app_commands.Choice(name=f"{label} ({value})", value=value)
            )

        return suggestions[:25]

    @staticmethod
    def _parse_role_color(raw_value: str | None) -> tuple[int | None, str]:
        if raw_value is None:
            return None, ""

        normalized = CTFRoleCampaigns._normalize_role_color_token(raw_value)
        if not normalized:
            return None, ""
        if len(normalized) != 6 or not re.fullmatch(r"[0-9a-f]{6}", normalized):
            return None, (
                "ロールカラーは 6 桁の16進数で入力してください。"
                "(例: #ff6600)"
            )
        return int(normalized, 16), ""

    def _pick_unique_channel_name(
        self,
        *,
        category: discord.CategoryChannel,
        base_name: str,
    ) -> str:
        existing_names = {
            text_channel.name for text_channel in category.text_channels
        }
        if base_name not in existing_names:
            return base_name

        for suffix in range(2, 1000):
            candidate = self._build_channel_name_with_suffix(base_name, suffix)
            if candidate not in existing_names:
                return candidate
        return self._build_channel_name_with_suffix(base_name, 1000)

    async def _ensure_ctf_category(
        self, guild: discord.Guild
    ) -> discord.CategoryChannel:
        for category in guild.categories:
            if category.name.strip().lower() == CTF_CATEGORY_NAME:
                return category

        return await guild.create_category(
            CTF_CATEGORY_NAME,
            reason="Create CTF category for ctf-role campaigns",
        )

    async def _ensure_archive_category(
        self, guild: discord.Guild
    ) -> discord.CategoryChannel:
        for category in guild.categories:
            if category.name.strip().lower() == ARCHIVE_CATEGORY_NAME:
                return category

        return await guild.create_category(
            ARCHIVE_CATEGORY_NAME,
            reason="Create archive category for ctf-role campaigns",
        )

    async def _create_ctf_discussion_channel(
        self,
        *,
        guild: discord.Guild,
        draft: CampaignDraft,
        role: discord.Role,
        creator: discord.Member | None,
        creator_id: int,
    ) -> discord.TextChannel:
        category = await self._ensure_ctf_category(guild)
        base_name = self._build_channel_base_name(draft.ctf_name)
        channel_name = self._pick_unique_channel_name(
            category=category,
            base_name=base_name,
        )

        topic = f"{draft.ctf_name} discussion channel"
        bot_member = self._resolve_bot_member(guild)
        overwrites = self._build_discussion_channel_overwrites(
            default_role=guild.default_role,
            role=role,
            creator=creator,
            bot_member=bot_member,
        )

        return await guild.create_text_channel(
            name=channel_name,
            category=category,
            topic=topic,
            overwrites=overwrites,
            reason=f"Create CTF discussion channel by {creator_id}",
        )

    async def _archive_discussion_channel(
        self,
        *,
        guild: discord.Guild,
        campaign: CTFRoleCampaign,
        role: discord.Role | None,
        reason: str,
    ) -> bool:
        if campaign.discussion_channel_id is None:
            return False

        discussion_channel = await self._resolve_text_channel(
            guild, campaign.discussion_channel_id
        )
        if discussion_channel is None:
            return False

        try:
            archive_category = await self._ensure_archive_category(guild)
            await discussion_channel.edit(category=archive_category, reason=reason)
            await discussion_channel.set_permissions(
                guild.default_role,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                reason=reason,
            )
            if role is not None:
                await discussion_channel.set_permissions(
                    role,
                    overwrite=None,
                    reason=reason,
                )
            await send_message_safely(
                discussion_channel,
                content=(
                    "📦 このCTFは終了しました。"
                    "チャンネルを archive に移動し、全体公開に切り替えました。"
                ),
            )
            return True
        except (discord.Forbidden, discord.HTTPException) as error:
            logger.warning(
                "Failed to archive discussion channel for campaign=%s guild=%s "
                "channel=%s",
                campaign.id,
                guild.id,
                campaign.discussion_channel_id,
                exc_info=error,
            )
            return False

    @staticmethod
    def _resolve_role_announce_channel(
        guild: discord.Guild,
    ) -> discord.TextChannel | None:
        for text_channel in guild.text_channels:
            if text_channel.name.strip().lower() == ROLE_ANNOUNCE_CHANNEL_NAME:
                return text_channel
        return None

    def _build_recruitment_message(
        self,
        *,
        draft: CampaignDraft,
        role: discord.Role,
        discussion_channel: discord.TextChannel,
    ) -> str:
        start_text = self.usecase.format_unix_datetime(draft.start_at_unix)
        if draft.end_at_unix is None:
            end_text = "常設(手動で /ctf-role close)"
        else:
            end_text = self.usecase.format_unix_datetime(draft.end_at_unix)

        return (
            f"📣 **{draft.ctf_name}** 参加者募集\n"
            f"開始: {start_text}\n"
            f"終了: {end_text}\n"
            f"CTFチャンネル: {discussion_channel.mention}\n"
            f"{REACTION_EMOJI} を付けると {role.mention} を付与します。\n"
            f"{REACTION_EMOJI} を外すと {role.mention} を剥奪します。"
        )

    def _format_campaign_line(self, campaign: CTFRoleCampaign) -> str:
        start_text = self.usecase.format_unix_datetime(campaign.start_at_unix)
        end_text = (
            self.usecase.format_unix_datetime(campaign.end_at_unix)
            if campaign.end_at_unix is not None
            else "常設"
        )
        return (
            f"- {campaign.ctf_name} | status={campaign.status.value} | "
            f"start={start_text} | end={end_text} | by=<@{campaign.created_by}>"
        )

    async def _cleanup_created_resources(
        self,
        *,
        discussion_channel: discord.TextChannel | None,
        role: discord.Role | None,
        message: discord.Message | None,
    ) -> None:
        if message is not None:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                logger.warning("Failed to clean up recruitment message: %s", message.id)
        if role is not None:
            try:
                await role.delete(reason="Cleanup after failed campaign creation")
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                logger.warning("Failed to clean up role: %s", role.id)
        if discussion_channel is not None:
            try:
                await discussion_channel.delete(
                    reason="Cleanup after failed campaign creation"
                )
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                logger.warning(
                    "Failed to clean up discussion channel: %s",
                    discussion_channel.id,
                )

    async def _mark_campaign_message_closed(
        self, guild: discord.Guild, campaign: CTFRoleCampaign
    ) -> bool:
        channel = await self._resolve_text_channel(guild, campaign.channel_id)
        if channel is None:
            return False

        try:
            message = await channel.fetch_message(campaign.message_id)
        except discord.NotFound:
            return True
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Failed to fetch campaign message for close: "
                "guild=%s channel=%s message=%s",
                campaign.guild_id,
                campaign.channel_id,
                campaign.message_id,
            )
            return False

        if message.content.startswith(CLOSED_HEADER):
            return True

        try:
            await message.edit(content=f"{CLOSED_HEADER}\n\n{message.content}")
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Failed to edit campaign close message: %s", message.id)
            return False
        return True

    async def _close_campaign(
        self,
        campaign: CTFRoleCampaign,
        *,
        reason: str,
    ) -> CloseCampaignReport:
        closed = await asyncio.to_thread(
            self.usecase.close_campaign,
            campaign_id=campaign.id,
        )
        if not closed:
            return CloseCampaignReport(was_closed=False)

        warnings: list[str] = []
        guild = self.bot.get_guild(campaign.guild_id)
        if guild is None:
            warnings.append("guild_not_found")
            return CloseCampaignReport(was_closed=True, warnings=tuple(warnings))

        role = await self._resolve_role(guild, campaign.role_id)
        archived = await self._archive_discussion_channel(
            guild=guild,
            campaign=campaign,
            role=role,
            reason=reason,
        )
        if not archived:
            warnings.append("discussion_archive_failed")

        if role is not None:
            try:
                await role.delete(reason=reason)
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Failed to delete role for campaign: %s", campaign.id)
                warnings.append("role_delete_failed")

        message_closed = await self._mark_campaign_message_closed(guild, campaign)
        if not message_closed:
            warnings.append("message_update_failed")

        return CloseCampaignReport(was_closed=True, warnings=tuple(warnings))

    async def _handle_reaction_event(
        self, payload: discord.RawReactionActionEvent, *, add_role: bool
    ) -> None:
        if payload.guild_id is None:
            return
        if str(payload.emoji) != REACTION_EMOJI:
            return

        bot_user = self.bot.user
        if bot_user is not None and payload.user_id == bot_user.id:
            return

        campaign = await asyncio.to_thread(
            self.usecase.find_active_campaign_by_message,
            guild_id=payload.guild_id,
            channel_id=payload.channel_id,
            message_id=payload.message_id,
        )
        if campaign is None:
            return
        if self.usecase.is_campaign_expired(campaign):
            await self._close_campaign(campaign, reason="Campaign expired")
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        member = payload.member if add_role else None
        if member is None:
            member = await self._fetch_member(guild, payload.user_id)
        if member is None or member.bot:
            return

        role = guild.get_role(campaign.role_id)
        if role is None:
            return

        try:
            if add_role:
                if role not in member.roles:
                    await member.add_roles(
                        role,
                        reason=f"Joined CTF role: {campaign.ctf_name}",
                    )
            elif role in member.roles:
                await member.remove_roles(
                    role,
                    reason=f"Left CTF role: {campaign.ctf_name}",
                )
        except discord.Forbidden:
            logger.warning(
                "Role operation forbidden for campaign=%s user=%s",
                campaign.id,
                member.id,
            )
        except discord.HTTPException:
            logger.exception(
                "Role operation failed for campaign=%s user=%s",
                campaign.id,
                member.id,
            )

    @app_commands.command(name="create", description="CTF募集メッセージを作成します。")
    @app_commands.describe(
        ctf_name="CTF名",
        role_color="ロールカラー(任意, #RRGGBB / 候補あり)",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        ctf_name: str,
        role_color: str | None = None,
    ) -> None:
        if interaction.guild is None:
            await send_interaction_message(
                interaction,
                "このコマンドはサーバー内でのみ使用できます。",
                ephemeral=True,
            )
            return

        role_color_value, color_error = self._parse_role_color(role_color)
        if color_error:
            await send_interaction_message(
                interaction,
                color_error,
                ephemeral=True,
            )
            return

        modal = CTFRoleCreateModal(
            self,
            ctf_name=ctf_name,
            role_color_value=role_color_value,
        )
        await interaction.response.send_modal(modal)

    @create.autocomplete("role_color")
    async def create_role_color_autocomplete(
        self,
        _interaction: discord.Interaction,
        current: str,
    ) -> builtins.list[app_commands.Choice[str]]:
        return self._build_role_color_suggestions(current)

    async def handle_create_modal_submit(
        self,
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
            self.usecase.validate_campaign_draft,
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
        announce_channel = self._resolve_role_announce_channel(guild)
        if announce_channel is None:
            await interaction.followup.send(
                "`role` という名前のテキストチャンネルが見つかりません。"
                "募集メッセージの投稿先として `#role` を作成してください。",
                ephemeral=True,
            )
            return

        discussion_channel: discord.TextChannel | None = None
        role: discord.Role | None = None
        message: discord.Message | None = None

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
                interaction.user
                if isinstance(interaction.user, discord.Member)
                else None
            )
            discussion_channel = await self._create_ctf_discussion_channel(
                guild=guild,
                draft=draft,
                role=role,
                creator=creator_member,
                creator_id=interaction.user.id,
            )
            content = self._build_recruitment_message(
                draft=draft,
                role=role,
                discussion_channel=discussion_channel,
            )
            message = await send_message_safely(announce_channel, content=content)
            if message is None:
                raise RuntimeError("Failed to send recruitment message.")
            await message.add_reaction(REACTION_EMOJI)

            await asyncio.to_thread(
                self.usecase.create_campaign,
                guild_id=guild.id,
                channel_id=announce_channel.id,
                message_id=message.id,
                role_id=role.id,
                discussion_channel_id=discussion_channel.id,
                created_by=interaction.user.id,
                draft=draft,
            )
        except discord.Forbidden:
            await self._cleanup_created_resources(
                discussion_channel=discussion_channel,
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
            await self._cleanup_created_resources(
                discussion_channel=discussion_channel,
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
            await self._cleanup_created_resources(
                discussion_channel=discussion_channel,
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
        await interaction.followup.send(
            "募集を作成しました: "
            f"{message.jump_url}\n"
            f"募集投稿先: {announce_channel.mention}\n"
            f"CTFチャンネル: {discussion_channel.mention}",
            ephemeral=True,
        )

    @app_commands.command(name="list", description="CTF募集一覧を表示します。")
    @app_commands.describe(status="表示対象(default: active)")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="active", value=STATUS_ACTIVE),
            app_commands.Choice(name="closed", value=STATUS_CLOSED),
            app_commands.Choice(name="all", value=STATUS_ALL),
        ]
    )
    async def list(
        self,
        interaction: discord.Interaction,
        status: app_commands.Choice[str] | None = None,
    ) -> None:
        if interaction.guild is None:
            await send_interaction_message(
                interaction,
                "このコマンドはサーバー内でのみ使用できます。",
                ephemeral=True,
            )
            return

        selected_status = status.value if status is not None else STATUS_ACTIVE
        campaigns = await asyncio.to_thread(
            self.usecase.list_campaigns,
            guild_id=interaction.guild.id,
            status=selected_status,
            limit=LIST_LIMIT,
        )
        if not campaigns:
            await send_interaction_message(
                interaction,
                "表示対象の募集はありません。",
                ephemeral=True,
            )
            return

        lines = [self._format_campaign_line(campaign) for campaign in campaigns]
        content = "\n".join(lines)
        if len(content) > 1900:
            content = f"{content[:1897]}..."

        await send_interaction_message(interaction, content, ephemeral=True)

    @app_commands.command(name="close", description="CTF募集を終了します。")
    @app_commands.describe(ctf_name="終了対象のCTF名")
    async def close(self, interaction: discord.Interaction, ctf_name: str) -> None:
        if interaction.guild is None:
            await send_interaction_message(
                interaction,
                "このコマンドはサーバー内でのみ使用できます。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        campaign = await asyncio.to_thread(
            self.usecase.find_active_campaign_by_name,
            guild_id=interaction.guild.id,
            ctf_name=ctf_name,
        )
        if campaign is None:
            await interaction.followup.send(
                "指定名の active 募集は見つかりませんでした。",
                ephemeral=True,
            )
            return

        if not self._can_close_campaign(interaction.user, campaign):
            await interaction.followup.send(
                "募集を終了できるのは作成者または "
                "Manage Server 権限を持つユーザーのみです。",
                ephemeral=True,
            )
            return

        report = await self._close_campaign(
            campaign,
            reason=f"CTF role campaign closed by {interaction.user.id}",
        )
        if not report.was_closed:
            await interaction.followup.send(
                "この募集はすでに終了済みです。",
                ephemeral=True,
            )
            return

        if report.warnings:
            warning_text = ", ".join(report.warnings)
            await interaction.followup.send(
                f"`{campaign.ctf_name}` を終了しました。"
                f"ただし後処理で一部失敗があります: {warning_text}",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"`{campaign.ctf_name}` を終了し、ロールを削除しました。",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        await self._handle_reaction_event(payload, add_role=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        await self._handle_reaction_event(payload, add_role=False)

    @tasks.loop(minutes=1)
    async def close_expired_campaigns(self) -> None:
        campaigns = await asyncio.to_thread(self.usecase.list_due_campaigns, limit=20)
        for campaign in campaigns:
            await self._close_campaign(campaign, reason="CTF campaign end_at reached")

    @close_expired_campaigns.before_loop
    async def before_close_expired_campaigns(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CTFRoleCampaigns(bot))
