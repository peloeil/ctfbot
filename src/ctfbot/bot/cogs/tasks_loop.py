import os
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import time, timezone, timedelta


class TasksLoop(commands.Cog):
    JST = timezone(timedelta(hours=+9), "JST")

    def __init__(self, bot):
        load_dotenv()
        self.bot = bot
        self.channel_id = int(os.getenv("BOT_CHANNEL_ID") or "")
        self.goodmorning.start()

    @tasks.loop(time=[time(hour=4, minute=47, tzinfo=JST)])
    async def goodmorning(self):
        channel = self.bot.get_channel(self.channel_id)
        if channel is not None:
            try:
                await channel.send("おはよう！朝4時に何してるんだい？")
            except discord.DiscordException as e:
                print(f"Failed to send message: {e}")
        else:
            print("Channel not found. Check the channel ID.")


async def setup(bot):
    await bot.add_cog(TasksLoop(bot))
