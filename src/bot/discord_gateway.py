import logging

import discord
from discord.ext import commands


class DiscordGateway:
    def __init__(self, bot: commands.Bot, logger: logging.Logger):
        self._bot = bot
        self._logger = logger

    async def resolve_messageable_channel(
        self, channel_id: int
    ) -> discord.abc.Messageable | None:
        if channel_id <= 0:
            return None

        channel = self._bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._bot.fetch_channel(channel_id)
            except discord.NotFound, discord.Forbidden, discord.HTTPException:
                self._logger.exception("Failed to resolve channel: %s", channel_id)
                return None

        if not isinstance(channel, discord.abc.Messageable):
            self._logger.warning("Configured channel %s is not messageable", channel_id)
            return None
        return channel
