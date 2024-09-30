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

    @commands.command(description="Rolls a dice in NdN format")
    async def roll(self, ctx, dice: str):
        """
        Rolls a dice in NdN format.
        N is a positive integer in (0, 100].
        The first N is the number of dice to roll, the second N is the number of sides on each die.
        Example: !roll 3d6
        """
        dice_pattern = re.compile(r"^(\d+)d(\d+)$")
        match = dice_pattern.match(dice)
        if not match:
            await ctx.send("Format must be in NdN! Example: !roll 3d6")
            return

        rolls, limit = map(int, dice.split("d"))

        if rolls <= 0 or limit <= 0:
            await ctx.send("Both values must be positive!")
            return
        if rolls > 100:
            await ctx.send("You can roll a maximum of 100 dice at once.")
            return
        if limit > 100:
            await ctx.send("The maximum number of sides on a die is 100.")
            return
        results = [random.randint(1, limit) for _ in range(rolls)]
        total = sum(results)
        result_str = ", ".join(map(str, results))
        await ctx.send(f"Rolls: {result_str}\nTotal: {total}")

async def setup(bot):
    await bot.add_cog(Misc(bot))
