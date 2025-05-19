import os
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import time, timezone, timedelta


import requests
from bs4 import BeautifulSoup

def get_alpacahack_solves(user):
    response = requests.get(f"https://alpacahack.com/users/{user}")
    soup = BeautifulSoup(response.content, features="html.parser")
    tbody = soup.find("tbody",class_="MuiTableBody-root")
    ret = f"{user}\n"
    for i in tbody.find_all("tr"):
        data = i.find_all("td")
        challenge = data[0].find("a").text
        solves = data[1].find("p").text
        solve_at = data[2].find("p").text
        ret += f"`{'CHALLENGE':10}: {challenge} {'SOLVED AT':10}: {solve_at}`\n"
    return ret


class Alpacahack(commands.Cog):
    JST = timezone(timedelta(hours=+9), "JST")

    def __init__(self, bot):
        load_dotenv()
        self.bot = bot
        self.channel_id = int(os.getenv("BOT_CHANNLE_ID") or "0")
        self.alpacahack_solves.start()

    @tasks.loop(time=[time(hour=20, minute=45, tzinfo=JST)])
    async def alpacahack_solves(self):
        channel = self.bot.get_channel(self.channel_id)
        if channel is not None:
            try:
                await channel.send(get_alpacahack_solves("tor-ato"))
            except discord.DiscordException as e:
                print(f"Failed to send message: {e}")
        else:
            print("Channel not found. Check the channel ID.")


async def setup(bot):
    await bot.add_cog(Alpacahack(bot))
