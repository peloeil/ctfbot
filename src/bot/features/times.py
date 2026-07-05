import re

import discord
from discord import app_commands
from discord.ext import commands

from bot.helpers import send_interaction

MAX_CHANNELS_PER_COMMAND = 10


def _normalize_channel_name(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9\-]", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized


class TimesChannels(commands.GroupCog, group_name="times"):
    CATEGORY_NAME = "times"

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(
        name="create", description="timesカテゴリにテキストチャンネルを作成します。"
    )
    @app_commands.describe(names="作成するチャンネル名 (カンマ区切りで複数指定可)")
    async def create_times(self, interaction: discord.Interaction, names: str) -> None:
        guild = interaction.guild
        if guild is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        category = discord.utils.get(guild.categories, name=self.CATEGORY_NAME)
        if category is None:
            await send_interaction(interaction, "times カテゴリが見つかりません。")
            return

        requested = list(
            dict.fromkeys(
                normalized
                for raw in re.split(r"[,、\n]+", names)
                if (normalized := _normalize_channel_name(raw))
            )
        )
        if not requested:
            await send_interaction(
                interaction, "作成するチャンネル名を入力してください。"
            )
            return
        if len(requested) > MAX_CHANNELS_PER_COMMAND:
            await send_interaction(
                interaction, "一度に作成できるチャンネルは 10 個までです。"
            )
            return

        existing = {channel.name for channel in category.text_channels}
        created: list[str] = []
        skipped: list[str] = []
        for name in requested:
            if name in existing:
                skipped.append(name)
                continue
            await guild.create_text_channel(name=name, category=category)
            existing.add(name)
            created.append(name)

        lines: list[str] = []
        if created:
            lines.append(
                "✅ " + ", ".join(f"#{name}" for name in created) + " を作成しました。"
            )
        if skipped:
            lines.append(
                "⏭️ " + ", ".join(f"#{name}" for name in skipped) + " は既に存在します。"
            )
        await send_interaction(interaction, "\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TimesChannels(bot))
