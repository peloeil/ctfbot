import re

import discord
from discord import app_commands
from discord.ext import commands

from bot.helpers import log_audit, send_interaction
from bot.runtime import get_runtime

MAX_CHANNEL_NAME_LENGTH = 100


def _normalize_channel_name(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9\-]", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized[:MAX_CHANNEL_NAME_LENGTH]


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
        guild = interaction.guild
        if guild is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        category_id = self.settings.times_category_id
        if category_id is None:
            await send_interaction(interaction, "times 機能が設定されていません。")
            return
        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            await send_interaction(interaction, "times カテゴリが見つかりません。")
            return

        normalized = _normalize_channel_name(name)
        if not normalized:
            await send_interaction(
                interaction, "作成するチャンネル名を入力してください。"
            )
            return
        if any(channel.name == normalized for channel in category.text_channels):
            await send_interaction(interaction, f"⏭️ #{normalized} は既に存在します。")
            return

        channel = await guild.create_text_channel(name=normalized, category=category)
        await send_interaction(interaction, f"✅ #{channel.name} を作成しました。")
        await log_audit(
            self.bot,
            interaction,
            command_name="times create",
            details=[f"作成: {channel.mention}"],
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TimesChannels(bot))
