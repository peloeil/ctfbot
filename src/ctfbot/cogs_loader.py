from discord.ext import commands

DEFAULT_EXTENSIONS = (
    "ctfbot.features.utility",
    "ctfbot.features.times",
    "ctfbot.features.alpacahack.cog",
    "ctfbot.features.ctfteam.cog",
    "ctfbot.features.ctftime",
    "ctfbot.features.audit_log",
    "ctfbot.features.sudo.cog",
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
