from __future__ import annotations

import asyncio
import datetime

import discord
from discord.ext import commands, tasks

from ...cogs._runtime import get_runtime
from ...discord_gateway import DiscordGateway
from ...errors import ExternalAPIError
from ...utils.helpers import logger, send_message_safely
from .models import CTFEvent


class CTFTimeNotifications(commands.Cog):
    """Weekly CTFtime notifier and on-demand check command."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = get_runtime(bot)
        self.settings = self.runtime.settings
        self.usecase = self.runtime.ctftime_usecase
        self.gateway = DiscordGateway(bot, logger)
        self.timezone_label = getattr(
            self.settings.tzinfo, "key", self.settings.timezone
        )
        self.weekly_ctf_notification.change_interval(
            time=self.settings.ctftime_notification_time
        )
        self.weekly_ctf_notification.start()

    @staticmethod
    def _can_operate_in_channel(
        user: discord.abc.User, channel: discord.abc.Messageable
    ) -> bool:
        if not isinstance(user, discord.Member):
            return False
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return False

        permissions = channel.permissions_for(user)
        can_send = (
            permissions.send_messages_in_threads
            if isinstance(channel, discord.Thread)
            else permissions.send_messages
        )
        return permissions.view_channel and can_send

    async def cog_unload(self) -> None:
        self.weekly_ctf_notification.cancel()

    async def _resolve_target_channel(
        self, fallback: discord.abc.Messageable | None = None
    ) -> discord.abc.Messageable | None:
        if fallback is not None:
            return fallback
        return await self.gateway.resolve_messageable_channel(
            self.settings.bot_channel_id
        )

    @tasks.loop()
    async def weekly_ctf_notification(self) -> None:
        if datetime.datetime.now(self.settings.tzinfo).weekday() != 0:
            return
        await self.send_upcoming_ctfs()

    @weekly_ctf_notification.before_loop
    async def before_weekly_notification(self) -> None:
        await self.bot.wait_until_ready()

    async def send_upcoming_ctfs(
        self, target_channel: discord.abc.Messageable | None = None
    ) -> None:
        channel = await self._resolve_target_channel(target_channel)
        if channel is None:
            return

        try:
            events = await asyncio.to_thread(self.usecase.get_upcoming_events)
        except ExternalAPIError:
            await send_message_safely(
                channel,
                content=(
                    "❌ CTF情報の取得中にエラーが発生しました。"
                    "しばらく後に再試行してください。"
                ),
            )
            return
        except Exception:
            logger.exception("Failed to fetch CTFtime events")
            await send_message_safely(
                channel,
                content="❌ CTF情報の取得中に予期しないエラーが発生しました。",
            )
            return

        if not events:
            await send_message_safely(
                channel,
                content=(
                    f"📅 **今後{self.settings.ctftime_window_days}日間のCTF予定**\n\n"
                    "現在予定されているCTFはありません。"
                ),
            )
            return

        embed = self._build_events_embed(events)
        await send_message_safely(channel, embed=embed)

    def _build_events_embed(self, events: list[CTFEvent]) -> discord.Embed:
        embed = discord.Embed(
            title=f"📅 今後{self.settings.ctftime_window_days}日間のCTF予定",
            description=f"CTFtimeから取得した{len(events)}件のCTF情報",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(self.settings.tzinfo),
        )

        for index, event in enumerate(events[:25], start=1):
            start_time = event.start.strftime("%m/%d %H:%M")
            end_time = event.finish.strftime("%m/%d %H:%M")
            duration_hours = int((event.finish - event.start).total_seconds() / 3600)
            field_value = (
                f"🕐 **開始**: {start_time} {self.timezone_label}\n"
                f"🏁 **終了**: {end_time} {self.timezone_label}\n"
                f"⏱️ **期間**: {duration_hours}時間\n"
                f"🔗 [CTFtime]({event.ctftime_url})"
            )
            embed.add_field(
                name=f"{index}. {event.title}",
                value=field_value,
                inline=False,
            )

        embed.set_footer(
            text=(
                "CTFtime API経由で取得 | 毎週月曜日 "
                f"{self.settings.ctftime_notification_time.strftime('%H:%M')} に更新"
            )
        )
        return embed

    @commands.command(name="ctf")
    async def manual_ctf_check(self, ctx: commands.Context) -> None:
        if not self._can_operate_in_channel(ctx.author, ctx.channel):
            await send_message_safely(
                ctx.channel,
                content="このチャンネルを閲覧・投稿できるメンバーのみ利用できます。",
            )
            return

        await send_message_safely(ctx.channel, content="🔄 CTF情報を取得中...")
        await self.send_upcoming_ctfs(target_channel=ctx.channel)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CTFTimeNotifications(bot))
