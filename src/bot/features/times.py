from discord.ext import commands


class TimesChannels(commands.GroupCog, group_name="times"):
    CATEGORY_NAME = "times"

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TimesChannels(bot))
