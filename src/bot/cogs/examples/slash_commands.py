"""
Slash commands cog for the CTF Discord bot.
Contains slash commands for message management.
"""

from discord import app_commands
from discord.ext import commands


class SlashCommandsExample(commands.Cog):
    """Cog for slash commands like echo"""

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


async def setup(bot):
    """
    Add the SlashCommands cog to the bot.

    Args:
        bot: The bot instance
    """
    await bot.add_cog(SlashCommandsExample(bot))
