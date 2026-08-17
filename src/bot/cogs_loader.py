from discord.ext import commands

DEFAULT_EXTENSIONS = (
    "bot.features.utility",
    "bot.features.times",
    "bot.features.alpacahack",
    "bot.features.ctfteam.cog",
    "bot.features.ctftime",
    "bot.features.audit_log",
    "bot.features.sudo.cog",
)


async def load_cogs(
    bot: commands.Bot,
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
) -> None:
    for ext in extensions:
        try:
            await bot.load_extension(ext)
        except Exception as exc:
            raise RuntimeError(f"Failed to load extension: {ext}") from exc
