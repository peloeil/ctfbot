"""
Slash commands cog for the CTF Discord bot.
Contains slash commands for message management.
"""
import re
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

from ..utils.helpers import handle_error


class SlashCommands(commands.Cog):
    """Cog for slash commands like echo, pin, and unpin."""
    
    # Regex for Discord message links
    MESSAGE_LINK_REGEX = re.compile(r"^https://discord\.com/channels/(\d+)/(\d+)/(\d+)$")
    
    def __init__(self, bot):
        """
        Initialize the SlashCommands cog.
        
        Args:
            bot: The bot instance
        """
        self.bot = bot

    @app_commands.command(name="echo")
    async def echo(self, interaction, message: str):
        """
        Echo back a message.
        
        Args:
            interaction: Command interaction
            message: Message to echo
        """
        await interaction.response.send_message(message)

    async def _get_message_from_link(self, interaction, link: str) -> Optional[discord.Message]:
        """
        Get a Discord message from a message link.
        
        Args:
            interaction: Command interaction
            link: Discord message link
            
        Returns:
            The message object or None if not found/accessible
        """
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
        except discord.Forbidden:
            await interaction.response.send_message("このメッセージを取得する権限がありません。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(handle_error(e, "メッセージの取得に失敗しました"), ephemeral=True)
            
        return None

    @app_commands.command(name="pin", description="指定されたメッセージをピン留めします。")
    @app_commands.describe(link="Discord message link")
    async def pin(self, interaction, link: str):
        """
        Pin a message.
        
        Args:
            interaction: Command interaction
            link: Discord message link to pin
        """
        message = await self._get_message_from_link(interaction, link)
        if not message:
            return
            
        try:
            await message.pin()
            await interaction.response.send_message("メッセージをピン留めしました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("このメッセージをピン留めする権限がありません。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(handle_error(e, "メッセージのピン留めに失敗しました"), ephemeral=True)
    
    @app_commands.command(name="unpin", description="指定されたメッセージのピン留めを解除します。")
    @app_commands.describe(link="Discord message link")
    async def unpin(self, interaction, link: str):
        """
        Unpin a message.
        
        Args:
            interaction: Command interaction
            link: Discord message link to unpin
        """
        message = await self._get_message_from_link(interaction, link)
        if not message:
            return
            
        try:
            await message.unpin()
            await interaction.response.send_message("メッセージのピン留めを解除しました。", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("このメッセージのピン留めを解除する権限がありません。", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(handle_error(e, "メッセージのピン留め解除に失敗しました"), ephemeral=True)


async def setup(bot):
    """
    Add the SlashCommands cog to the bot.
    
    Args:
        bot: The bot instance
    """
    await bot.add_cog(SlashCommands(bot))
