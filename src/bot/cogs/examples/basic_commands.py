"""
Basic commands cog for the CTF Discord bot.
Contains simple text commands and dice rolling functionality.
"""

import random
import re

from discord.ext import commands

from ...utils.helpers import handle_error, send_message_safely


class BasicCommandsExample(commands.Cog):
    """Cog for basic bot commands like ping, greetings, and dice rolling."""

    def __init__(self, bot: commands.Bot) -> None:
        """
        Initialize the BasicCommands cog.

        Args:
            bot: The bot instance
        """
        self.bot = bot

    @commands.command()
    async def ping(self, ctx: commands.Context) -> None:
        """Simple command to check if the bot is responsive."""
        await send_message_safely(ctx.channel, content="pong!")

    @commands.command()
    async def hello(self, ctx: commands.Context) -> None:
        """Greet the user who invoked the command."""
        await send_message_safely(ctx.channel, content=f"Hello, {ctx.author.mention}!")

    @commands.command(aliases=["gn", "おやすみ"])
    async def goodnight(self, ctx: commands.Context) -> None:
        """Wish the user goodnight."""
        await send_message_safely(
            ctx.channel, content=f"Have a good night, {ctx.author.mention}!"
        )

    @commands.command(aliases=["gm", "おは", "おはよ", "おはよう"])
    async def goodmorning(self, ctx: commands.Context) -> None:
        """Wish the user good morning."""
        await send_message_safely(
            ctx.channel, content=f"Good morning, {ctx.author.mention}!"
        )

    @commands.command()
    async def roll(self, ctx: commands.Context, dice: str = "1d100") -> None:
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
                await send_message_safely(
                    ctx.channel, content="Format must be in NdM!\nExample: !roll 3d6"
                )
                return

            rolls, limit = map(int, match.groups())

            if rolls <= 0 or rolls > 100 or limit <= 0 or limit > 100:
                await send_message_safely(
                    ctx.channel,
                    content=(
                        "Constraints violation: Must use 1-100 dice with 1-100 sides"
                    ),
                )
                return

            if rolls == 1:
                result = random.randint(1, limit)
                await send_message_safely(ctx.channel, content=f"1d{limit}: {result}")
                return

            results = [random.randint(1, limit) for _ in range(rolls)]
            total = sum(results)
            result_str = ", ".join(map(str, results))
            await send_message_safely(
                ctx.channel, content=f"{rolls}d{limit}: {result_str}\nTotal: {total}"
            )
        except Exception as e:
            await send_message_safely(
                ctx.channel, content=handle_error(e, "Error in roll command")
            )


async def setup(bot: commands.Bot) -> None:
    """
    Add the BasicCommands cog to the bot.

    Args:
        bot: The bot instance
    """
    await bot.add_cog(BasicCommandsExample(bot))
