"""
Manage cogs commands for the CTF Discord bot.
Provides commands for loading, unloading, and reloading cogs.
"""
from discord import app_commands
from discord.ext import commands

from ..utils.helpers import handle_error


class ManageCogs(commands.Cog):
    """Cog for managing other cogs (loading, unloading, reloading)."""

    def __init__(self, bot):
        """
        Initialize the ManageCogs cog.
        
        Args:
            bot: The bot instance
        """
        self.bot = bot

    @app_commands.command(name="sync")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def sync(self, interaction):
        """
        Sync slash commands with Discord.
        Requires moderate_members permission.
        """
        try:
            synced = await self.bot.tree.sync()
            await interaction.response.send_message(f"Synced {len(synced)} command(s)")
        except Exception as e:
            await interaction.response.send_message(
                handle_error(e, "Failed to sync commands")
            )

    @app_commands.command(name="load")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def load(self, interaction, name: str):
        """
        Load a cog.
        Requires moderate_members permission.
        
        Args:
            interaction: Command interaction
            name: Name of the cog to load
        """
        try:
            # Fix the module path to use correct prefix
            await self.bot.load_extension(f"bot.cogs.{name}")
            await interaction.response.send_message(f"Loaded {name}")
        except Exception as e:
            await interaction.response.send_message(
                handle_error(e, f"Failed to load {name}")
            )

    @app_commands.command(name="unload")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unload(self, interaction, name: str):
        """
        Unload a cog.
        Requires moderate_members permission.
        
        Args:
            interaction: Command interaction
            name: Name of the cog to unload
        """
        try:
            # Fix the module path to use correct prefix
            await self.bot.unload_extension(f"bot.cogs.{name}")
            await interaction.response.send_message(f"Unloaded {name}")
        except Exception as e:
            await interaction.response.send_message(
                handle_error(e, f"Failed to unload {name}")
            )

    @app_commands.command(name="reload")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def reload(self, interaction, name: str):
        """
        Reload a cog.
        Requires moderate_members permission.
        
        Args:
            interaction: Command interaction
            name: Name of the cog to reload
        """
        try:
            # Fix the module path to use correct prefix
            await self.bot.reload_extension(f"bot.cogs.{name}")
            await interaction.response.send_message(f"Reloaded {name}")
        except Exception as e:
            await interaction.response.send_message(
                handle_error(e, f"Failed to reload {name}")
            )


async def setup(bot):
    """
    Add the ManageCogs cog to the bot.
    
    Args:
        bot: The bot instance
    """
    await bot.add_cog(ManageCogs(bot))
