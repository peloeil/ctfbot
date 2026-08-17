from dataclasses import dataclass

from discord.ext import commands

from ctfbot.config import Settings
from ctfbot.db import Database


@dataclass(frozen=True, slots=True)
class BotRuntime:
    settings: Settings
    db: Database


def get_runtime(bot: commands.Bot) -> BotRuntime:
    runtime = getattr(bot, "runtime", None)
    if not isinstance(runtime, BotRuntime):
        raise RuntimeError("Bot runtime is not configured.")
    return runtime
