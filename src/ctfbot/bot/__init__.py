import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
from .cogs_loader import load_cogs


def create_bot():
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"{bot.user} has connected to Discord!")
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")

    return bot


async def run_bot(bot):
    load_dotenv()
    await load_cogs(bot)
    await bot.start(os.getenv("DISCORD_TOKEN"))
