import re

import discord
from discord import app_commands
from discord.ext import commands

from ..utils.helpers import logger, send_interaction_message


class SlashCommands(commands.Cog):
    """Slash commands for echo/pin/unpin/perms utilities."""

    MESSAGE_LINK_REGEX = re.compile(
        r"^https://discord\.com/channels/(\d+)/(\d+)/(\d+)$"
    )
    CHANNEL_NAME_SEPARATOR_REGEX = re.compile(r"[,、\n]+")
    TIMES_CATEGORY_NAME = "times"
    MAX_CHANNEL_NAME_LENGTH = 100

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _format_perm(value: bool) -> str:
        return "✅" if value else "❌"

    @staticmethod
    def _can_operate_in_channel(
        user: discord.abc.User, channel: discord.TextChannel
    ) -> bool:
        if not isinstance(user, discord.Member):
            return False
        permissions = channel.permissions_for(user)
        return permissions.view_channel and permissions.send_messages

    @classmethod
    def _normalize_channel_name(cls, raw_name: str) -> str:
        normalized = raw_name.strip().lower().replace("_", "-")
        normalized = re.sub(r"\s+", "-", normalized)
        normalized = re.sub(r"[^\w-]", "-", normalized)
        normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
        trimmed = normalized[: cls.MAX_CHANNEL_NAME_LENGTH].strip("-")
        return trimmed

    @classmethod
    def _parse_channel_names(cls, raw_names: str) -> tuple[list[str], list[str]]:
        tokens = [
            token.strip()
            for token in cls.CHANNEL_NAME_SEPARATOR_REGEX.split(raw_names)
            if token.strip()
        ]
        normalized_names: list[str] = []
        invalid_names: list[str] = []
        seen: set[str] = set()

        for token in tokens:
            normalized = cls._normalize_channel_name(token)
            if not normalized:
                invalid_names.append(token)
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            normalized_names.append(normalized)

        return normalized_names, invalid_names

    @classmethod
    def _resolve_times_category(
        cls, guild: discord.Guild
    ) -> discord.CategoryChannel | None:
        for category in guild.categories:
            if category.name.strip().lower() == cls.TIMES_CATEGORY_NAME:
                return category
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

    @app_commands.command(name="echo")
    async def echo(self, interaction: discord.Interaction, message: str) -> None:
        await send_interaction_message(interaction, message, ephemeral=False)

    async def _get_message_from_link(
        self, interaction: discord.Interaction, link: str
    ) -> discord.Message | None:
        match = self.MESSAGE_LINK_REGEX.match(link)
        if not match:
            await send_interaction_message(
                interaction,
                "無効なメッセージリンクです。",
                ephemeral=True,
            )
            return None

        if interaction.guild is None:
            await send_interaction_message(
                interaction,
                "このコマンドはサーバー内でのみ使用できます。",
                ephemeral=True,
            )
            return None

        guild_id, channel_id, message_id = map(int, match.groups())
        if guild_id != interaction.guild.id:
            await send_interaction_message(
                interaction,
                "このサーバーのメッセージリンクではありません。",
                ephemeral=True,
            )
            return None

        channel = interaction.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await send_interaction_message(
                interaction,
                "指定されたチャンネルが見つかりません。",
                ephemeral=True,
            )
            return None

        if not self._can_operate_in_channel(interaction.user, channel):
            await send_interaction_message(
                interaction,
                "そのチャンネルを閲覧・投稿できるメンバーのみ利用できます。",
                ephemeral=True,
            )
            return None

        try:
            return await channel.fetch_message(message_id)
        except discord.NotFound:
            await send_interaction_message(
                interaction,
                "指定されたメッセージは見つかりませんでした。",
                ephemeral=True,
            )
        except discord.Forbidden:
            await send_interaction_message(
                interaction,
                "このメッセージを取得する権限がありません。",
                ephemeral=True,
            )
        except discord.HTTPException:
            logger.exception("Failed to fetch message from link")
            await send_interaction_message(
                interaction,
                "メッセージの取得に失敗しました。",
                ephemeral=True,
            )
        return None

    @app_commands.command(
        name="pin", description="指定されたメッセージをピン留めします。"
    )
    @app_commands.describe(link="Discord message link")
    async def pin(self, interaction: discord.Interaction, link: str) -> None:
        message = await self._get_message_from_link(interaction, link)
        if message is None:
            return

        try:
            await message.pin()
            await send_interaction_message(
                interaction,
                f"{interaction.user} がメッセージをピン留めしました。",
                ephemeral=False,
            )
        except discord.Forbidden:
            await send_interaction_message(
                interaction,
                "このメッセージをピン留めする権限がありません。",
            )
        except discord.HTTPException:
            logger.exception("Failed to pin message")
            await send_interaction_message(
                interaction,
                "メッセージのピン留めに失敗しました。",
            )

    @app_commands.command(
        name="unpin", description="指定されたメッセージのピン留めを解除します。"
    )
    @app_commands.describe(link="Discord message link")
    async def unpin(self, interaction: discord.Interaction, link: str) -> None:
        message = await self._get_message_from_link(interaction, link)
        if message is None:
            return

        try:
            await message.unpin()
            await send_interaction_message(
                interaction,
                f"{interaction.user} がメッセージのピン留めを解除しました。",
                ephemeral=False,
            )
        except discord.Forbidden:
            await send_interaction_message(
                interaction,
                "このメッセージのピン留めを解除する権限がありません。",
            )
        except discord.HTTPException:
            logger.exception("Failed to unpin message")
            await send_interaction_message(
                interaction,
                "メッセージのピン留め解除に失敗しました。",
            )

    @app_commands.command(
        name="perms",
        description="このサーバー/チャンネルでのbot権限を表示します。",
    )
    @app_commands.describe(channel="確認対象チャンネル(省略時は実行チャンネル)")
    async def perms(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        if interaction.guild is None:
            await send_interaction_message(
                interaction,
                "このコマンドはサーバー内でのみ使用できます。",
                ephemeral=True,
            )
            return

        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await send_interaction_message(
                interaction,
                "確認対象はテキストチャンネルを指定してください。",
                ephemeral=True,
            )
            return

        bot_user = self.bot.user
        if bot_user is None:
            await send_interaction_message(
                interaction,
                "botユーザー情報を取得できませんでした。",
                ephemeral=True,
            )
            return

        bot_member = await self._fetch_member(interaction.guild, bot_user.id)
        if bot_member is None:
            await send_interaction_message(
                interaction,
                "このサーバーでのbotメンバー情報を取得できませんでした。",
                ephemeral=True,
            )
            return

        guild_perms = bot_member.guild_permissions
        channel_perms = target_channel.permissions_for(bot_member)

        guild_checks = {
            "Manage Roles": guild_perms.manage_roles,
            "Manage Channels": guild_perms.manage_channels,
            "Manage Messages": guild_perms.manage_messages,
        }
        channel_checks = {
            "View Channel": channel_perms.view_channel,
            "Send Messages": channel_perms.send_messages,
            "Add Reactions": channel_perms.add_reactions,
            "Manage Messages": channel_perms.manage_messages,
        }

        guild_lines = [
            f"- {self._format_perm(ok)} {name}"
            for name, ok in guild_checks.items()
        ]
        channel_lines = [
            f"- {self._format_perm(ok)} {name}"
            for name, ok in channel_checks.items()
        ]

        content = "\n".join(
            [
                f"Bot: {bot_member.mention}",
                f"Top Role: `{bot_member.top_role.name}` "
                f"(position={bot_member.top_role.position})",
                "",
                "**Guild Permissions**",
                *guild_lines,
                "",
                f"**Channel Permissions ({target_channel.mention})**",
                *channel_lines,
            ]
        )
        if len(content) > 1900:
            content = f"{content[:1897]}..."

        await send_interaction_message(interaction, content, ephemeral=True)

    @app_commands.command(
        name="create-times",
        description="timesカテゴリにテキストチャンネルを作成します。",
    )
    @app_commands.describe(
        names="作成するチャンネル名(カンマ/改行区切りで複数指定可)"
    )
    async def create_times(self, interaction: discord.Interaction, names: str) -> None:
        if interaction.guild is None:
            await send_interaction_message(
                interaction,
                "このコマンドはサーバー内でのみ使用できます。",
                ephemeral=True,
            )
            return

        requested_names, invalid_names = self._parse_channel_names(names)
        if not requested_names and not invalid_names:
            await send_interaction_message(
                interaction,
                "チャンネル名を入力してください。",
                ephemeral=True,
            )
            return

        times_category = self._resolve_times_category(interaction.guild)
        if times_category is None:
            await send_interaction_message(
                interaction,
                "`times` カテゴリが見つかりません。"
                "先に管理者がカテゴリを作成してください。",
                ephemeral=True,
            )
            return

        bot_user = self.bot.user
        if bot_user is None:
            await send_interaction_message(
                interaction,
                "botユーザー情報を取得できませんでした。",
                ephemeral=True,
            )
            return

        bot_member = await self._fetch_member(interaction.guild, bot_user.id)
        if bot_member is None:
            await send_interaction_message(
                interaction,
                "このサーバーでのbotメンバー情報を取得できませんでした。",
                ephemeral=True,
            )
            return

        category_perms = times_category.permissions_for(bot_member)
        if not category_perms.manage_channels:
            await send_interaction_message(
                interaction,
                "Botに `times` カテゴリでチャンネルを作成する権限がありません。"
                "(Manage Channels)",
                ephemeral=True,
            )
            return

        existing_names = {channel.name.lower() for channel in times_category.channels}
        created_mentions: list[str] = []
        skipped_names: list[str] = []
        failed_names: list[str] = []
        for channel_name in requested_names:
            if channel_name in existing_names:
                skipped_names.append(channel_name)
                continue
            try:
                created_channel = await times_category.create_text_channel(
                    channel_name,
                    reason=(
                        f"Created by /create-times requested by {interaction.user.id}"
                    ),
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.exception(
                    "Failed to create times channel: guild=%s channel=%s",
                    interaction.guild.id,
                    channel_name,
                )
                failed_names.append(channel_name)
                continue
            existing_names.add(channel_name)
            created_mentions.append(created_channel.mention)

        summary_lines = ["`times` カテゴリの作成結果:"]
        if created_mentions:
            summary_lines.append(f"- 作成: {', '.join(created_mentions)}")
        if skipped_names:
            summary_lines.append(
                "- 既存のためスキップ: "
                + ", ".join(f"`{name}`" for name in skipped_names)
            )
        if failed_names:
            summary_lines.append(
                "- 作成失敗: " + ", ".join(f"`{name}`" for name in failed_names)
            )
        if invalid_names:
            summary_lines.append(
                "- 無効な入力: " + ", ".join(f"`{name}`" for name in invalid_names)
            )
        if len(summary_lines) == 1:
            summary_lines.append("- 処理対象がありませんでした。")

        content = "\n".join(summary_lines)
        if len(content) > 1900:
            content = f"{content[:1897]}..."

        await send_interaction_message(interaction, content, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SlashCommands(bot))
