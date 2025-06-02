"""
Cogs loader module for the CTF Discord bot.
Handles loading and management of bot cogs.
"""


async def load_cogs(bot) -> None:
    """
    Load all cogs for the bot.

    Args:
        bot: The bot instance to load cogs for
    """
    extensions = [
        "bot.cogs.examples.basic_commands",
        "bot.cogs.manage_cogs",
        "bot.cogs.slash_commands",
        "bot.cogs.alpacahack",
    ]

    for cog in extensions:
        try:
            await bot.load_extension(cog)
            print(f"Loaded extension: {cog}")
        except Exception as e:
            print(f"Failed to load extension {cog}: {e}")
