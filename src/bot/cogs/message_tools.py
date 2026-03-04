import re

import discord
from discord import app_commands
from discord.ext import commands

from ..utils.helpers import logger, send_interaction_message


class MessageTools(commands.Cog):
    """Slash commands for echo/pin/unpin utilities."""

    MESSAGE_LINK_REGEX = re.compile(
        r"^https://discord\.com/channels/(\d+)/(\d+)/(\d+)$"
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _can_operate_in_channel(
        user: discord.abc.User, channel: discord.TextChannel
    ) -> bool:
        if not isinstance(user, discord.Member):
            return False
        permissions = channel.permissions_for(user)
        return permissions.view_channel and permissions.send_messages

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


async def setup(bot: commands.Bot):
    await bot.add_cog(MessageTools(bot))
