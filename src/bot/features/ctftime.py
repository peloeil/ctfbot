from discord.ext import commands

from bot.app import get_runtime


class CTFTimeNotifications(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        runtime = get_runtime(bot)
        self.bot = bot
        self.settings = runtime.settings


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CTFTimeNotifications(bot))
