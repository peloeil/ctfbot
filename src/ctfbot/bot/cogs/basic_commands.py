import re
import random
from discord.ext import commands


class BasicCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def ping(self, ctx):
        await ctx.send("pong!")

    @commands.command()
    async def hello(self, ctx):
        await ctx.send(f"Hello, {ctx.author.mention}!")

    @commands.command()
    async def goodnight(self, ctx):
        await ctx.send(f"Have a good night, {ctx.author.mention}!")

    @commands.command()
    async def roll(self, ctx, dice: str = "1d100"):
        dice_pattern = re.compile(r"^(\d+)d(\d+)$")
        match = dice_pattern.match(dice)
        if not match:
            await ctx.send("Format must be in NdM!\nExample: !roll 3d6")
            return

        rolls, limit = map(int, match.groups())

        if rolls <= 0 or 100 < rolls or limit <= 0 or 100 < limit:
            await ctx.send("Constraints violation")
            return
        if rolls == 1:
            await ctx.send(f"1d{limit}: {random.randint(1, limit)}")
            return
        results = [random.randint(1, limit) for _ in range(rolls)]
        total = sum(results)
        result_str = ", ".join(map(str, results))
        await ctx.send(f"{rolls}d{limit}: {result_str}\nTotal: {total}")


async def setup(bot):
    await bot.add_cog(BasicCommands(bot))
