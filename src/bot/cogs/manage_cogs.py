from discord import app_commands
from discord.ext import commands


class ManageCogs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="sync")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def sync(self, interaction):
        synced = await self.bot.tree.sync()
        await interaction.response.send_message(f"Synced {len(synced)} command(s)")

    @app_commands.command(name="load")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def load(self, interaction, name: str):
        try:
            await self.bot.load_extension(f"ctfbot.bot.cogs.{name}")
            await interaction.response.send_message(f"Loaded {name}")
        except Exception as e:
            await interaction.response.send_message(f"Error loading {name}: {e}")

    @app_commands.command(name="unload")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unload(self, interaction, name: str):
        try:
            await self.bot.unload_extension(f"ctfbot.bot.cogs.{name}")
            await interaction.response.send_message(f"Unloaded {name}")
        except Exception as e:
            await interaction.response.send_message(f"Error unloading {name}: {e}")

    @app_commands.command(name="reload")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def reload(self, interaction, name: str):
        try:
            await self.bot.reload_extension(f"ctfbot.bot.cogs.{name}")
            await interaction.response.send_message(f"Reloaded {name}")
        except Exception as e:
            await interaction.response.send_message(f"Error reloading {name}: {e}")


async def setup(bot):
    await bot.add_cog(ManageCogs(bot))
