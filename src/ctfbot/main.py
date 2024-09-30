import os
from dotenv import load_dotenv
import discord
from discord.ext import commands

extensions = {"!": ["ctfbot.cogs.misc"]}


class DiscordBot(commands.Bot):
    def __init__(self, prefix):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=prefix, intents=intents)

    async def setup_hook(self):
        for cogs in extensions[self.command_prefix]:
            await self.load_extension(cogs)

    async def on_ready(self):
        print(f"{self.user} has connected to Discord!")


def main():
    load_dotenv()
    bot = DiscordBot(prefix="!")
    bot.run(os.getenv("DISCORD_TOKEN"))


if __name__ == "__main__":
    main()
