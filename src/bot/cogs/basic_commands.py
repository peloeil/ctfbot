"""
Basic commands cog for the CTF Discord bot.
Contains simple text commands and dice rolling functionality.
"""
import re
import random
from discord.ext import commands

from ..utils.helpers import handle_error


class BasicCommands(commands.Cog):
    """Cog for basic bot commands like ping, greetings, and dice rolling."""

    def __init__(self, bot):
        """
        Initialize the BasicCommands cog.
        
        Args:
            bot: The bot instance
        """
        self.bot = bot

    @commands.command()
    async def ping(self, ctx):
        """Simple command to check if the bot is responsive."""
        await ctx.send("pong!")

    @commands.command()
    async def hello(self, ctx):
        """Greet the user who invoked the command."""
        await ctx.send(f"Hello, {ctx.author.mention}!")

    @commands.command(aliases=["gn", "おやすみ"])
    async def goodnight(self, ctx):
        """Wish the user goodnight."""
        await ctx.send(f"Have a good night, {ctx.author.mention}!")

    @commands.command(aliases=["gm", "おは", "おはよ", "おはよう"])
    async def goodmorning(self, ctx):
        """Wish the user good morning."""
        await ctx.send(f"Good morning, {ctx.author.mention}!")

    @commands.command()
    async def roll(self, ctx, dice: str = "1d100"):
        """
        Roll dice in NdM format.
        
        Args:
            ctx: Command context
            dice: Dice notation in NdM format (N dice with M sides)
        """
        try:
            dice_pattern = re.compile(r"^(\d+)d(\d+)$")
            match = dice_pattern.match(dice)
            if not match:
                await ctx.send("Format must be in NdM!\nExample: !roll 3d6")
                return

            rolls, limit = map(int, match.groups())

            if rolls <= 0 or 100 < rolls or limit <= 0 or 100 < limit:
                await ctx.send(
                    "Constraints violation: Must use 1-100 dice with 1-100 sides"
                )
                return

            if rolls == 1:
                result = random.randint(1, limit)
                await ctx.send(f"1d{limit}: {result}")
                return

            results = [random.randint(1, limit) for _ in range(rolls)]
            total = sum(results)
            result_str = ", ".join(map(str, results))
            await ctx.send(f"{rolls}d{limit}: {result_str}\nTotal: {total}")
        except Exception as e:
            await ctx.send(handle_error(e, "Error in roll command"))


async def setup(bot):
    """
    Add the BasicCommands cog to the bot.
    
    Args:
        bot: The bot instance
    """
    await bot.add_cog(BasicCommands(bot))
