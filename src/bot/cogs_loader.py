from discord.ext import commands

DEFAULT_EXTENSIONS = (
    "bot.features.utility",
    "bot.features.times",
    "bot.features.alpacahack",
    "bot.features.ctf_team.cog",
    "bot.features.ctftime",
    "bot.features.audit_log",
)


async def load_cogs(bot: commands.Bot) -> None:
    for ext in DEFAULT_EXTENSIONS:
        try:
            await bot.load_extension(ext)
        except Exception as exc:
            raise RuntimeError(f"Failed to load extension: {ext}") from exc
