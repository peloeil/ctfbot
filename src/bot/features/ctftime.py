import asyncio
import datetime
import time
from dataclasses import dataclass
from typing import cast

import discord
import requests
from discord import app_commands
from discord.ext import commands, tasks

from bot.errors import ExternalAPIError
from bot.helpers import resolve_messageable, send_interaction, send_safely
from bot.log import logger
from bot.runtime import get_runtime


@dataclass(frozen=True, slots=True)
class CTFEvent:
    title: str
    start: datetime.datetime
    finish: datetime.datetime
    ctftime_url: str


class CTFTimeClient:
    def __init__(
        self,
        *,
        timezone: datetime.tzinfo,
        user_agent: str,
        request_timeout: int = 10,
        max_retries: int = 3,
        retry_backoff: float = 1.5,
    ) -> None:
        self._timezone = timezone
        self._user_agent = user_agent
        self._timeout = request_timeout
        self._max_retries = max_retries
        self._backoff = retry_backoff

    def fetch_events(self, days: int, limit: int) -> list[CTFEvent]:
        now = datetime.datetime.now(self._timezone)
        start_unix = int(now.timestamp())
        finish_unix = int((now + datetime.timedelta(days=days)).timestamp())
        url = (
            "https://ctftime.org/api/v1/events/"
            f"?limit={limit}&start={start_unix}&finish={finish_unix}"
        )
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = requests.get(
                    url,
                    headers={"User-Agent": self._user_agent},
                    timeout=self._timeout,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, list):
                    raise ExternalAPIError("Unexpected CTFtime response.")
                return [self._parse_event(item) for item in payload]
            except (requests.RequestException, ValueError, ExternalAPIError) as exc:
                last_error = exc
                if attempt < self._max_retries:
                    time.sleep(self._backoff * attempt)
        raise ExternalAPIError("CTFtime からの取得に失敗しました。") from last_error

    def _parse_event(self, item: object) -> CTFEvent:
        if not isinstance(item, dict):
            raise ExternalAPIError("Unexpected CTFtime event.")
        raw = cast(dict[str, object], item)
        title = str(raw.get("title", "Untitled"))
        start_raw = raw.get("start")
        finish_raw = raw.get("finish")
        if start_raw is None or finish_raw is None:
            raise ExternalAPIError("Unexpected CTFtime event.")
        start = _parse_iso_datetime(str(start_raw)).astimezone(self._timezone)
        finish = _parse_iso_datetime(str(finish_raw)).astimezone(self._timezone)
        ctftime_url = str(raw.get("ctftime_url") or raw.get("url") or "")
        return CTFEvent(
            title=title, start=start, finish=finish, ctftime_url=ctftime_url
        )


def _parse_iso_datetime(value: str) -> datetime.datetime:
    normalized = value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
    parsed = datetime.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.UTC)
    return parsed


def _build_events_embed(events: list[CTFEvent], window_days: int) -> discord.Embed:
    embed = discord.Embed(title=f"📅 今後{window_days}日間のCTFイベント")
    if not events:
        embed.description = "予定されているイベントはありません。"
        return embed
    lines: list[str] = []
    for event in events:
        start_unix = int(event.start.timestamp())
        finish_unix = int(event.finish.timestamp())
        block = (
            f"**{event.title}**\n"
            f"🕐 <t:{start_unix}:f> 〜 <t:{finish_unix}:f>\n"
            f"🔗 [CTFtime]({event.ctftime_url})"
        )
        candidate = "\n\n".join([*lines, block])
        if len(candidate) > 4096:
            break
        lines.append(block)
    embed.description = "\n\n".join(lines)
    return embed


class CTFTimeNotifications(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        runtime = get_runtime(bot)
        self.bot = bot
        self.settings = runtime.settings
        self.client = CTFTimeClient(
            timezone=self.settings.tzinfo,
            user_agent=self.settings.ctftime_user_agent,
        )
        self.weekly_ctf_notification.change_interval(
            time=self.settings.ctftime_notification_time
        )
        self.weekly_ctf_notification.start()

    async def cog_unload(self) -> None:
        self.weekly_ctf_notification.cancel()

    @tasks.loop(hours=24)
    async def weekly_ctf_notification(self) -> None:
        try:
            if datetime.datetime.now(self.settings.tzinfo).weekday() != 0:
                return
            channel = await resolve_messageable(
                self.bot, self.settings.ctftime_channel_id
            )
            if channel is None:
                return
            try:
                events = await asyncio.to_thread(
                    self.client.fetch_events,
                    self.settings.ctftime_window_days,
                    self.settings.ctftime_event_limit,
                )
            except ExternalAPIError:
                logger.exception("Failed to fetch CTFtime events")
                await send_safely(channel, "CTFtime からの取得に失敗しました。")
                return
            embed = _build_events_embed(events, self.settings.ctftime_window_days)
            await send_safely(channel, embed=embed)
        except Exception:
            logger.exception("Error in weekly_ctf_notification")

    @weekly_ctf_notification.before_loop
    async def before_weekly(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="ctftime", description="CTFtimeの予定を手動で取得します。"
    )
    async def manual_ctf_check(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        await interaction.response.defer()
        try:
            events = await asyncio.to_thread(
                self.client.fetch_events,
                self.settings.ctftime_window_days,
                self.settings.ctftime_event_limit,
            )
        except ExternalAPIError:
            await send_interaction(
                interaction, "CTFtime からの取得に失敗しました。", ephemeral=False
            )
            return
        embed = _build_events_embed(events, self.settings.ctftime_window_days)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CTFTimeNotifications(bot))
