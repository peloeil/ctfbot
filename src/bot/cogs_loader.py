async def load_cogs(bot):
    extensions = [
        "bot.cogs.manage_cogs",
        "bot.cogs.basic_commands",
        "bot.cogs.slash_commands",
        "bot.cogs.tasks_loop",
        "bot.cogs.alpacahack"
    ]
    for cog in extensions:
        await bot.load_extension(cog)
