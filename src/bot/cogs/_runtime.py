from discord.ext import commands

from ..runtime import BotRuntime


def get_runtime(bot: commands.Bot) -> BotRuntime:
    runtime = getattr(bot, "runtime", None)
    if not isinstance(runtime, BotRuntime):
        raise RuntimeError("Bot runtime is not configured.")
    return runtime
