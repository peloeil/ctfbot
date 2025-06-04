"""
CTFtime notifications cog for the CTF Discord bot.
Fetches upcoming CTF events from CTFtime and sends weekly notifications.
"""

from datetime import datetime, time, timedelta

import discord
from ctftime_api import CTFTimeClient
from discord.ext import commands, tasks

from ..config import BOT_CHANNEL_ID, JST
from ..utils.helpers import logger, send_message_safely


class CTFTimeNotifications(commands.Cog):
    """Cog for CTFtime notifications that run weekly."""

    def __init__(self, bot: commands.Bot) -> None:
        """
        Initialize the CTFTimeNotifications cog.

        Args:
            bot: The bot instance
        """
        self.bot = bot
        self.ctftime_client = CTFTimeClient()
        self.weekly_ctf_notification.start()

    @tasks.loop(time=[time(hour=9, minute=0, tzinfo=JST)])
    async def weekly_ctf_notification(self) -> None:
        """
        Scheduled task to send weekly CTF notifications every Monday at 9:00 AM JST.
        """
        # Check if today is Monday (weekday() returns 0 for Monday)
        if datetime.now(JST).weekday() == 0:
            await self.send_upcoming_ctfs()

    async def send_upcoming_ctfs(self) -> None:
        """Fetch and send upcoming CTF events for the next 2 weeks."""
        channel = self.bot.get_channel(BOT_CHANNEL_ID)
        if channel is None:
            logger.error("Channel not found. Check the BOT_CHANNEL_ID.")
            return
        if not isinstance(channel, discord.abc.Messageable):
            logger.error("Channel is not messageable. Check the channel ID.")
            return
        try:
            # Calculate date range for next 2 weeks
            now = datetime.now(JST)
            start_date = now
            end_date = now + timedelta(weeks=2)

            # Fetch events from CTFtime API
            events = await self.ctftime_client.get_events_information(
                start=start_date,
                end=end_date,
                limit=20,  # Limit to 20 events to avoid spam
            )

            if not events:
                message = (
                    "📅 **今後2週間のCTF予定**\n\n現在予定されているCTFはありません。"
                )
                await send_message_safely(channel, content=message)
                return

            # Create embed message
            embed = discord.Embed(
                title="📅 今後2週間のCTF予定",
                description=f"CTFtimeから取得した{len(events)}件のCTF情報",
                color=0x00FF00,
                timestamp=datetime.now(JST),
            )

            # Add events to embed (max 25 fields per embed)
            for i, event in enumerate(events[:25]):
                start_time = event.start.strftime("%m/%d %H:%M")
                end_time = event.finish.strftime("%m/%d %H:%M")
                duration_seconds = (event.finish - event.start).total_seconds()
                duration_hours = int(duration_seconds / 3600)

                field_value = (
                    f"🕐 **開始**: {start_time} JST\n"
                    f"🏁 **終了**: {end_time} JST\n"
                    f"⏱️ **期間**: {duration_hours}時間\n"
                    f"🔗 [CTFtime]({event.ctftime_url})"
                )

                embed.add_field(
                    name=f"{i + 1}. {event.title}", value=field_value, inline=False
                )

            # Add footer
            embed.set_footer(text="CTFtime API経由で取得 | 毎週月曜日9:00に更新")

            # Send message
            await send_message_safely(channel, embed=embed)

        except Exception as e:
            logger.error(f"Error fetching CTF events: {e}")
            error_message = (
                "❌ CTF情報の取得中にエラーが発生しました。"
                "しばらく後に再試行してください。"
            )
            await send_message_safely(channel, content=error_message)

    @commands.command(name="ctf")
    async def manual_ctf_check(self, ctx: commands.Context) -> None:
        """Manual command to check upcoming CTFs."""
        await send_message_safely(ctx.channel, content="🔄 CTF情報を取得中...")
        await self.send_upcoming_ctfs()

    def cog_unload(self) -> None:
        """Clean up when the cog is unloaded."""
        self.weekly_ctf_notification.cancel()


async def setup(bot: commands.Bot) -> None:
    """
    Add the CTFTimeNotifications cog to the bot.

    Args:
        bot: The bot instance
    """
    await bot.add_cog(CTFTimeNotifications(bot))
