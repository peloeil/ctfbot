import random
import re
from discord.ext import commands


class Misc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def ping(self, ctx):
        await ctx.send("pong")

    @commands.command()
    async def hello(self, ctx):
        await ctx.send(f"Hello, {ctx.author.name}!")

    @commands.command(description="Rolls a dice in NdM format")
    async def roll(self, ctx, dice: str = commands.parameter(default="1d100", description="NdM format string")):
        """
        Rolls a dice in NdM format.

        N is the number of dice to roll.
        M is the number of sides on each die.

        constraints:
            N, M are integers.
            0 < N <= 100
            0 < M <= 100

        Example: !roll 3d6
        """
        dice_pattern = re.compile(r"^(\d+)d(\d+)$")
        if not dice_pattern.match(dice):
            await ctx.send("Format must be in NdN!\nExample: !roll 3d6")
            return

        rolls, limit = map(int, dice.split("d"))

        if rolls <= 0 or 100 < rolls or limit <= 0 or 100 < limit:
            await ctx.send("Constraint violation")
            return
        if rolls == 1:
            await ctx.send(f"1d100: {random.randint(1, limit)}")
            return
        results = [random.randint(1, limit) for _ in range(rolls)]
        total = sum(results)
        result_str = ", ".join(map(str, results))
        await ctx.send(f"{rolls}d{limit}: {result_str}\nTotal: {total}")


async def setup(bot):
    await bot.add_cog(Misc(bot))
