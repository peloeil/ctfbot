from discord.ext import commands

from bot.app import get_runtime


class Alpacahack(commands.GroupCog, group_name="alpaca"):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        runtime = get_runtime(bot)
        self.bot = bot
        self.settings = runtime.settings
        self.db = runtime.db


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Alpacahack(bot))
