from discord import app_commands
from discord.ext import commands
import discord
import re


class SlashCommands(commands.Cog):
    MESSAGE_LINK_REGEX = re.compile(r"^https://discord\.com/channels/(\d+)/(\d+)/(\d+)$")

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="echo")
    async def echo(self, interaction, message: str):
        await interaction.response.send_message(f"{message}")

    async def _get_message_from_link(self, interaction, link: str):
        match = self.MESSAGE_LINK_REGEX.match(link)
        if not match:
            await interaction.response.send_message("無効なメッセージリンクです。", ephemeral=True)
            return None
        guild_id, channel_id, message_id = map(int, match.groups())
        if guild_id != interaction.guild.id:
            await interaction.response.send_message("このサーバーのメッセージリンクではありません。", ephemeral=True)
            return None

        channel = interaction.guild.get_channel(channel_id)
        if channel is None:
            await interaction.response.send_message("指定されたチャンネルが見つかりません。", ephemeral=True)
            return None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("指定されたチャンネルはテキストチャンネルではありません。", ephemeral=True)
            return None
        try:
            message = await channel.fetch_message(message_id)
            return message
        except discord.NotFound:
            await interaction.response.send_message("指定されたメッセージは見つかりませんでした。", ephemeral=True)
            return None
        except discord.Forbidden:
            await interaction.response.send_message("このメッセージを取得する権限がありません。", ephemeral=True)
            return None
        except Exception as e:
            await interaction.response.send_message(f"メッセージの取得に失敗しました: {str(e)}", ephemeral=True)
            return None

    @app_commands.command(name="pin", description="指定されたメッセージをピン留めします。")
    @app_commands.describe(link="Discord message link")
    async def pin(self, interaction, link: str):
        message = await self._get_message_from_link(interaction, link)
        if not message:
            return
        try:
            await message.pin()
            await interaction.response.send_message("メッセージをピン留めしました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("このメッセージをピン留めする権限がありません。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"メッセージのピン留めに失敗しました: {str(e)}", ephemeral=True)
    
    @app_commands.command(name="unpin", description="指定されたメッセージのピン留めを解除します。")
    @app_commands.describe(link="Discord message link")
    async def unpin(self, interaction, link: str):
        message = await self._get_message_from_link(interaction, link)
        if not message:
            return
        try:
            await message.unpin()
            await interaction.response.send_message("メッセージのピン留めを解除しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("このメッセージのピン留めを解除する権限がありません。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"メッセージのピン留め解除に失敗しました: {str(e)}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(SlashCommands(bot))
