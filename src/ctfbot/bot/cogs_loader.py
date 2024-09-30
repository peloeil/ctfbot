async def load_cogs(bot):
    extensions = [
        "ctfbot.bot.cogs.manage_cogs",
        "ctfbot.bot.cogs.basic_commands",
        "ctfbot.bot.cogs.slash_commands",
    ]
    for cog in extensions:
        await bot.load_extension(cog)
