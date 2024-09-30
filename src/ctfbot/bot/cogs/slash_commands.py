from discord import app_commands
from discord.ext import commands


class SlashCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="echo")
    async def echo(self, interaction, message: str):
        await interaction.response.send_message(f"{message}")


async def setup(bot):
    await bot.add_cog(SlashCommands(bot))
