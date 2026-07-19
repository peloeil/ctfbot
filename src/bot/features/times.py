import re

import discord
from discord import app_commands
from discord.ext import commands

from bot.errors import ServiceError
from bot.helpers import log_audit, require_guild, send_interaction
from bot.runtime import get_runtime

MAX_CHANNEL_NAME_LENGTH = 100


def _normalize_channel_name(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9\-]", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized[:MAX_CHANNEL_NAME_LENGTH]


def _parse_times_channel_name(value: str) -> str:
    normalized = _normalize_channel_name(value)
    if not normalized:
        raise ServiceError("作成するチャンネル名を入力してください。")
    return normalized


def _require_times_category(
    guild: discord.Guild, category_id: int | None
) -> discord.CategoryChannel:
    if category_id is None:
        raise ServiceError("times 機能が設定されていません。")
    category = guild.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        raise ServiceError("times カテゴリが見つかりません。")
    return category


class TimesChannels(commands.GroupCog, group_name="times"):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        runtime = get_runtime(bot)
        self.bot = bot
        self.settings = runtime.settings

    @app_commands.command(
        name="create", description="timesカテゴリにテキストチャンネルを作成します。"
    )
    @app_commands.describe(name="作成するチャンネル名")
    async def create_times(self, interaction: discord.Interaction, name: str) -> None:
        try:
            guild = require_guild(interaction)
            category = _require_times_category(guild, self.settings.times_category_id)
            normalized = _parse_times_channel_name(name)
        except ServiceError as exc:
            await send_interaction(interaction, str(exc))
            return
        existing = next(
            (
                channel
                for channel in category.text_channels
                if channel.name == normalized
            ),
            None,
        )
        if existing is not None:
            await send_interaction(
                interaction, f"⏭️ {existing.mention} は既に存在します。"
            )
            return

        channel = await guild.create_text_channel(name=normalized, category=category)
        await send_interaction(interaction, f"✅ {channel.mention} を作成しました。")
        await log_audit(
            self.bot,
            interaction,
            command_name="times create",
            details=[f"作成: {channel.mention}"],
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TimesChannels(bot))
