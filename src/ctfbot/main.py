import os
from dotenv import load_dotenv
import discord
from discord.ext import commands

class DiscordBot(commands.Bot):
    def __init__(self, prefix):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=prefix, intents=intents)

    async def setup_hook(self):
        await self.load_extension("ctfbot.cogs.misc")
        #await self.load_extension("ctfbot.cogs.ctf")

    async def on_ready(self):
        print(f"{self.user} has connected to Discord!")

def main():
    load_dotenv()
    bot = DiscordBot(prefix="!")
    bot.run(os.getenv('DISCORD_TOKEN'))

if __name__ == "__main__":
    main()
