import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.errors import ConflictError, ServiceError
from bot.features.ctf_team import campaign, discord_ops
from bot.features.ctf_team.models import Campaign, CampaignStatus
from bot.helpers import (
    fetch_member,
    format_timestamp_with_relative,
    log_audit,
    send_interaction,
)
from bot.log import logger
from bot.runtime import get_runtime

REACTION_EMOJI = "✅"
ROLE_ANNOUNCE_CHANNEL_NAME = "role"

ROLE_COLOR_SUGGESTIONS = (
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


class CTFTeamCreateModal(discord.ui.Modal, title="CTF募集作成"):
    start_at = discord.ui.TextInput(
        label="開始日時 (YYYY-MM-DD HH:MM)",
        placeholder="2026-01-15 21:00",
        required=True,
        max_length=16,
    )
    end_at = discord.ui.TextInput(
        label="終了日時 (空欄で常設)",
        placeholder="2026-01-17 21:00",
        required=False,
        max_length=16,
    )

    def __init__(
        self, cog: CTFTeamCampaigns, ctf_name: str, role_color: discord.Colour
    ) -> None:
        super().__init__()
        self.cog = cog
        self.ctf_name = ctf_name
        self.role_color = role_color

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_create_submit(
            interaction,
            self.ctf_name,
            self.role_color,
            self.start_at.value,
            self.end_at.value,
        )


class CTFTeamCampaigns(commands.GroupCog, group_name="ctfteam"):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        runtime = get_runtime(bot)
        self.bot = bot
        self.settings = runtime.settings
        self.db = runtime.db
        self.start_due_campaigns.start()
        self.close_expired_campaigns.start()
        self.archive_closed_campaigns.start()

    async def cog_unload(self) -> None:
        self.start_due_campaigns.cancel()
        self.close_expired_campaigns.cancel()
        self.archive_closed_campaigns.cancel()

    @app_commands.command(name="open", description="CTF参加者の募集を作成します。")
    @app_commands.describe(
        ctf_name="CTF名",
        role_color="ロールの色 (例: #3b82f6)",
    )
    @app_commands.choices(
        role_color=[
            app_commands.Choice(name=name, value=hex_value)
            for name, hex_value in ROLE_COLOR_SUGGESTIONS
        ]
    )
    async def open_campaign(
        self,
        interaction: discord.Interaction,
        ctf_name: str,
        role_color: str = "#3b82f6",
    ) -> None:
        try:
            colour = discord.Colour(int(role_color.removeprefix("#"), 16))
        except ValueError:
            await send_interaction(
                interaction, "ロール色は #RRGGBB 形式で指定してください。"
            )
            return
        await interaction.response.send_modal(
            CTFTeamCreateModal(self, ctf_name, colour)
        )

    async def handle_create_submit(
        self,
        interaction: discord.Interaction,
        ctf_name: str,
        role_color: discord.Colour,
        start_at_raw: str,
        end_at_raw: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None or interaction.guild_id is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return

        try:
            draft = await asyncio.to_thread(
                campaign.validate_and_build_draft,
                self.db,
                guild_id=interaction.guild_id,
                created_by=interaction.user.id,
                ctf_name=ctf_name,
                start_at_raw=start_at_raw,
                end_at_raw=end_at_raw,
                timezone=self.settings.tzinfo,
            )
        except ServiceError as exc:
            await send_interaction(interaction, str(exc))
            return

        role: discord.Role | None = None
        discussion: discord.TextChannel | None = None
        voice: discord.VoiceChannel | None = None
        recruit_msg: discord.Message | None = None

        try:
            category = guild.get_channel(self.settings.ctf_team_category_id)
            if not isinstance(category, discord.CategoryChannel):
                raise ServiceError("CTF募集カテゴリが見つかりません。")
            role_channel = discord.utils.get(
                category.text_channels, name=ROLE_ANNOUNCE_CHANNEL_NAME
            )
            if role_channel is None:
                raise ServiceError("#role チャンネルが見つかりません。")

            role = await guild.create_role(
                name=draft.ctf_name, colour=role_color, mentionable=True
            )
            creator = guild.get_member(interaction.user.id)
            discussion = await discord_ops.create_discussion_channel(
                guild,
                category,
                draft.ctf_name,
                role,
                creator,
                guild.me,
            )
            voice = await discord_ops.create_voice_channel(
                guild,
                category,
                draft.ctf_name,
                role,
                creator,
                guild.me,
            )
            text = discord_ops.build_recruitment_message(draft, role, discussion)
            recruit_msg = await role_channel.send(text)
            await recruit_msg.add_reaction(REACTION_EMOJI)

            try:
                created = await asyncio.to_thread(
                    self.db.create_campaign,
                    guild_id=guild.id,
                    channel_id=role_channel.id,
                    message_id=recruit_msg.id,
                    role_id=role.id,
                    discussion_channel_id=discussion.id,
                    voice_channel_id=voice.id,
                    ctf_name=draft.ctf_name,
                    start_at_unix=draft.start_at_unix,
                    end_at_unix=draft.end_at_unix,
                    created_by=interaction.user.id,
                    created_at_unix=campaign.now_unix(self.settings.tzinfo),
                )
            except ConflictError:
                await discord_ops.cleanup_resources(
                    message=recruit_msg,
                    role=role,
                    discussion=discussion,
                    voice=voice,
                )
                await send_interaction(interaction, "同名の募集が既に作成されました。")
                return

            if isinstance(creator, discord.Member) and role not in creator.roles:
                await creator.add_roles(role)

            if campaign.is_started(created, self.settings.tzinfo):
                await discord_ops.send_start_announcement(
                    discussion, created.ctf_name, role
                )
                await asyncio.to_thread(
                    self.db.mark_started,
                    created.id,
                    campaign.now_unix(self.settings.tzinfo),
                )

            await send_interaction(
                interaction, f"**{draft.ctf_name}** の募集を作成しました。"
            )
            await log_audit(
                self.bot,
                interaction,
                command_name="ctfteam open",
                details=[f"CTF名: {draft.ctf_name}"],
            )
        except ServiceError as exc:
            await discord_ops.cleanup_resources(
                message=recruit_msg, role=role, discussion=discussion, voice=voice
            )
            await send_interaction(interaction, str(exc))
        except Exception:
            logger.exception("Failed to create campaign: %s", ctf_name)
            await discord_ops.cleanup_resources(
                message=recruit_msg, role=role, discussion=discussion, voice=voice
            )
            await send_interaction(interaction, "募集の作成中にエラーが発生しました。")

    @app_commands.command(name="list", description="CTF募集の一覧を表示します。")
    @app_commands.describe(status="表示するステータス")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="募集中", value="active"),
            app_commands.Choice(name="終了", value="closed"),
            app_commands.Choice(name="すべて", value="all"),
        ]
    )
    async def list_campaigns(
        self, interaction: discord.Interaction, status: str = "active"
    ) -> None:
        if interaction.guild_id is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        filter_status = None if status == "all" else CampaignStatus(status)
        campaigns = await asyncio.to_thread(
            self.db.list_campaigns,
            interaction.guild_id,
            filter_status,
        )
        embed = _build_campaigns_embed(
            interaction.guild_id, campaigns, _status_label(status)
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="close", description="CTF募集を終了します。")
    @app_commands.describe(ctf_name="終了するCTF名")
    async def close_campaign_cmd(
        self, interaction: discord.Interaction, ctf_name: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None or interaction.guild_id is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        found = await asyncio.to_thread(
            self.db.find_campaign_by_name,
            guild_id=interaction.guild_id,
            ctf_name=ctf_name.strip(),
            status=CampaignStatus.ACTIVE,
        )
        if found is None:
            await send_interaction(
                interaction, f"active 募集 '{ctf_name}' が見つかりません。"
            )
            return
        if not _can_manage_campaign(interaction, found):
            await send_interaction(interaction, "この募集を終了する権限がありません。")
            return

        archive_at = await self._close_campaign_resources(guild, found)
        if archive_at is None:
            await send_interaction(
                interaction,
                "Discord リソースの更新に失敗したため、募集を終了しませんでした。",
            )
            return
        await send_interaction(
            interaction,
            f"**{found.ctf_name}** を終了しました。archive 予定: "
            f"{format_timestamp_with_relative(archive_at)}",
        )
        await log_audit(
            self.bot,
            interaction,
            command_name="ctfteam close",
            details=[f"CTF名: {found.ctf_name}"],
        )

    @app_commands.command(
        name="archive", description="終了済み募集を手動でarchiveします。"
    )
    @app_commands.describe(ctf_name="archiveするCTF名")
    async def archive_campaign_cmd(
        self, interaction: discord.Interaction, ctf_name: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None or interaction.guild_id is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        found = await asyncio.to_thread(
            self.db.find_campaign_by_name,
            guild_id=interaction.guild_id,
            ctf_name=ctf_name.strip(),
            status=CampaignStatus.CLOSED,
            archived=False,
        )
        if found is None:
            await self._send_archive_not_found(interaction, ctf_name)
            return
        if not _can_manage_campaign(interaction, found):
            await send_interaction(
                interaction, "この募集を archive する権限がありません。"
            )
            return

        if not await self._archive_campaign_resources(guild, found):
            await send_interaction(
                interaction,
                "Discord リソースの archive に失敗したため、"
                "DB状態を更新しませんでした。",
            )
            return
        await send_interaction(
            interaction, f"**{found.ctf_name}** を archive しました。"
        )
        await log_audit(
            self.bot,
            interaction,
            command_name="ctfteam archive",
            details=[f"CTF名: {found.ctf_name}"],
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        if str(payload.emoji) != REACTION_EMOJI:
            return
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return
        if payload.guild_id is None:
            return
        found = await asyncio.to_thread(
            self.db.find_active_campaign_by_message,
            guild_id=payload.guild_id,
            channel_id=payload.channel_id,
            message_id=payload.message_id,
        )
        if found is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        if campaign.is_expired(found, self.settings.tzinfo):
            await self._close_campaign_resources(guild, found)
            return
        role = guild.get_role(found.role_id)
        if role is None:
            return
        member = await fetch_member(guild, payload.user_id)
        if member is None or role in member.roles:
            return
        try:
            await member.add_roles(role)
        except discord.Forbidden, discord.HTTPException:
            logger.warning("Failed to add role to member %s", payload.user_id)
            return
        if found.discussion_channel_id:
            disc_ch = guild.get_channel(found.discussion_channel_id)
            if isinstance(disc_ch, discord.TextChannel):
                await discord_ops.send_join_announcement(
                    disc_ch, member, found.ctf_name
                )

    @tasks.loop(minutes=1)
    async def start_due_campaigns(self) -> None:
        try:
            now = campaign.now_unix(self.settings.tzinfo)
            due = await asyncio.to_thread(self.db.list_due_starts, now)
            for item in due:
                guild = self.bot.get_guild(item.guild_id)
                if guild is None:
                    continue
                disc_ch = guild.get_channel(item.discussion_channel_id or 0)
                role = guild.get_role(item.role_id)
                if isinstance(disc_ch, discord.TextChannel) and role is not None:
                    await discord_ops.send_start_announcement(
                        disc_ch, item.ctf_name, role
                    )
                await asyncio.to_thread(
                    self.db.mark_started,
                    item.id,
                    campaign.now_unix(self.settings.tzinfo),
                )
        except Exception:
            logger.exception("Error in start_due_campaigns")

    @start_due_campaigns.before_loop
    async def before_start_due(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def close_expired_campaigns(self) -> None:
        try:
            now = campaign.now_unix(self.settings.tzinfo)
            due = await asyncio.to_thread(self.db.list_due_campaigns, now)
            for item in due:
                guild = self.bot.get_guild(item.guild_id)
                if guild is not None:
                    await self._close_campaign_resources(guild, item)
        except Exception:
            logger.exception("Error in close_expired_campaigns")

    @close_expired_campaigns.before_loop
    async def before_close_expired(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def archive_closed_campaigns(self) -> None:
        try:
            now = campaign.now_unix(self.settings.tzinfo)
            due = await asyncio.to_thread(self.db.list_due_archives, now)
            for item in due:
                guild = self.bot.get_guild(item.guild_id)
                if guild is not None:
                    await self._archive_campaign_resources(guild, item)
        except Exception:
            logger.exception("Error in archive_closed_campaigns")

    @archive_closed_campaigns.before_loop
    async def before_archive_closed(self) -> None:
        await self.bot.wait_until_ready()

    async def _send_archive_not_found(
        self, interaction: discord.Interaction, ctf_name: str
    ) -> None:
        if interaction.guild_id is None:
            await send_interaction(interaction, f"募集 '{ctf_name}' が見つかりません。")
            return
        active = await asyncio.to_thread(
            self.db.find_campaign_by_name,
            guild_id=interaction.guild_id,
            ctf_name=ctf_name.strip(),
            status=CampaignStatus.ACTIVE,
        )
        if active is not None:
            await send_interaction(
                interaction,
                f"'{ctf_name}' は募集中です。"
                "先に `/ctfteam close` で終了してください。",
            )
            return
        archived = await asyncio.to_thread(
            self.db.find_campaign_by_name,
            guild_id=interaction.guild_id,
            ctf_name=ctf_name.strip(),
            status=CampaignStatus.CLOSED,
            archived=True,
        )
        if archived is not None:
            await send_interaction(
                interaction, f"'{ctf_name}' は既に archive 済みです。"
            )
            return
        await send_interaction(interaction, f"募集 '{ctf_name}' が見つかりません。")

    async def _close_campaign_resources(
        self, guild: discord.Guild, item: Campaign
    ) -> int | None:
        closed_at, archive_at = campaign.calculate_close(self.settings.tzinfo)

        ok = True
        recruit_ch = guild.get_channel(item.channel_id)
        if isinstance(recruit_ch, discord.TextChannel):
            ok = await discord_ops.mark_message_closed(recruit_ch, item.message_id)
        ok = (
            await discord_ops.delete_voice_channel(
                self.bot, guild, item.voice_channel_id
            )
            and ok
        )
        if not ok:
            logger.warning("Failed to close Discord resources for campaign %s", item.id)
            return None

        was_closed = await asyncio.to_thread(
            self.db.close_campaign, item.id, closed_at, archive_at
        )
        if not was_closed:
            return item.archive_at_unix or archive_at

        disc_ch = guild.get_channel(item.discussion_channel_id or 0)
        role = guild.get_role(item.role_id)
        if isinstance(disc_ch, discord.TextChannel) and role is not None:
            await discord_ops.send_close_snapshot(disc_ch, item.ctf_name, role)
        return archive_at

    async def _archive_campaign_resources(
        self, guild: discord.Guild, item: Campaign
    ) -> bool:
        archive_category = guild.get_channel(self.settings.ctf_team_archive_category_id)
        if not isinstance(archive_category, discord.CategoryChannel):
            logger.warning(
                "Archive category %s not found",
                self.settings.ctf_team_archive_category_id,
            )
            return False

        ok = True
        disc_ch = guild.get_channel(item.discussion_channel_id or 0)
        role = guild.get_role(item.role_id)
        if isinstance(disc_ch, discord.TextChannel):
            ok = await discord_ops.archive_discussion_channel(
                disc_ch, archive_category, role, guild.me
            )
        ok = (
            await discord_ops.delete_voice_channel(
                self.bot, guild, item.voice_channel_id
            )
            and ok
        )
        if role is not None:
            try:
                await role.delete()
            except discord.Forbidden, discord.HTTPException:
                logger.warning("Failed to delete role %s", item.role_id)
                ok = False
        if not ok:
            logger.warning(
                "Failed to archive Discord resources for campaign %s", item.id
            )
            return False
        await asyncio.to_thread(
            self.db.mark_archived,
            item.id,
            campaign.now_unix(self.settings.tzinfo),
        )
        return True


def _can_manage_campaign(interaction: discord.Interaction, item: Campaign) -> bool:
    if item.created_by == interaction.user.id:
        return True
    permissions = getattr(interaction.user, "guild_permissions", None)
    return bool(permissions and permissions.manage_guild)


def _status_label(status: str) -> str:
    return {"active": "募集中", "closed": "終了", "all": "すべて"}.get(status, status)


def _build_campaigns_embed(
    guild_id: int, campaigns: list[Campaign], status_label: str
) -> discord.Embed:
    embed = discord.Embed(title=f"CTF募集一覧 ({status_label})")
    if not campaigns:
        embed.description = "該当する募集はありません。"
        return embed

    lines = [f"{len(campaigns)}件を表示しています。"]
    for index, item in enumerate(campaigns, start=1):
        block_lines = [
            f"**{index}. {item.ctf_name}**",
            f"状態: {'募集中' if item.status is CampaignStatus.ACTIVE else '終了'}",
            f"開始: {format_timestamp_with_relative(item.start_at_unix)}",
            "終了: "
            + (
                "常設"
                if item.end_at_unix is None
                else format_timestamp_with_relative(item.end_at_unix)
            ),
            "募集: "
            f"[メッセージへ移動](https://discord.com/channels/{guild_id}/"
            f"{item.channel_id}/{item.message_id})",
            f"議論: <#{item.discussion_channel_id}>"
            if item.discussion_channel_id
            else "議論: -",
            f"VC: <#{item.voice_channel_id}>" if item.voice_channel_id else "VC: -",
            f"ロール: <@&{item.role_id}>",
            f"作成者: <@{item.created_by}>",
        ]
        if item.status is CampaignStatus.CLOSED:
            block_lines.append(
                f"archive予定: {format_timestamp_with_relative(item.archive_at_unix)}"
            )
        block = "\n".join(block_lines)
        candidate = "\n\n".join([*lines, block])
        if len(candidate) > 4096:
            remaining = len(campaigns) - (len(lines) - 1)
            lines.append(f"他 {remaining} 件は省略しています。")
            break
        lines.append(block)
    embed.description = "\n\n".join(lines)
    return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CTFTeamCampaigns(bot))
