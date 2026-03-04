import re

import discord
from discord import app_commands
from discord.ext import commands

from ..utils.helpers import logger, send_interaction_message


class TimesChannels(commands.Cog):
    """Slash command for creating channels in times category."""

    CHANNEL_NAME_SEPARATOR_REGEX = re.compile(r"[,、\n]+")
    TIMES_CATEGORY_NAME = "times"
    MAX_CHANNEL_NAME_LENGTH = 100

    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
    await bot.add_cog(TimesChannels(bot))
