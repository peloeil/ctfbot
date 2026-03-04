import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.config import Settings  # noqa: E402
from bot.features.alpacahack.cog import Alpacahack  # noqa: E402
from bot.features.alpacahack.usecase import WeeklySolveSummary  # noqa: E402
from bot.features.ctftime.cog import CTFTimeNotifications  # noqa: E402
from bot.runtime import build_runtime  # noqa: E402


class _FakeBot(commands.Bot):
    def __init__(self, runtime):
        intents = discord.Intents.none()
        super().__init__(command_prefix="!", intents=intents)
        self.runtime = runtime


class CogTests(unittest.IsolatedAsyncioTestCase):
    def _build_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            timezone = ZoneInfo("Asia/Tokyo")
            settings = Settings(
                discord_token="token",
                command_prefix="!",
                bot_channel_id=123,
                bot_status_channel_id=0,
                timezone="Asia/Tokyo",
                tzinfo=timezone,
                log_level="INFO",
                database_path=str(Path(tmpdir) / "alpaca.db"),
                alpacahack_solve_time=datetime.time(23, 0, tzinfo=timezone),
                ctftime_notification_time=datetime.time(9, 0, tzinfo=timezone),
                ctftime_window_days=14,
                ctftime_event_limit=20,
                ctftime_user_agent="ctfbot-test/1.0",
            )
            return build_runtime(settings)

    async def test_ctftime_manual_check_denied_by_permission(self):
        runtime = self._build_runtime()
        fake_bot = _FakeBot(runtime)
        with patch("discord.ext.tasks.Loop.start", return_value=None):
            cog = CTFTimeNotifications(fake_bot)

        ctx = type("Ctx", (), {"author": object(), "channel": object()})()
        with (
            patch.object(cog, "_can_operate_in_channel", return_value=False),
            patch(
                "bot.features.ctftime.cog.send_message_safely", new=AsyncMock()
            ) as send_mock,
        ):
            await CTFTimeNotifications.manual_ctf_check.callback(cog, ctx)

        send_mock.assert_awaited_once_with(
            ctx.channel,
            content="このチャンネルを閲覧・投稿できるメンバーのみ利用できます。",
        )
        await fake_bot.close()

    async def test_ctftime_manual_check_fetches_when_allowed(self):
        runtime = self._build_runtime()
        fake_bot = _FakeBot(runtime)
        with patch("discord.ext.tasks.Loop.start", return_value=None):
            cog = CTFTimeNotifications(fake_bot)

        ctx = type("Ctx", (), {"author": object(), "channel": object()})()
        with (
            patch.object(cog, "_can_operate_in_channel", return_value=True),
            patch.object(cog, "send_upcoming_ctfs", new=AsyncMock()) as fetch_mock,
            patch(
                "bot.features.ctftime.cog.send_message_safely", new=AsyncMock()
            ) as send_mock,
        ):
            await CTFTimeNotifications.manual_ctf_check.callback(cog, ctx)

        send_mock.assert_awaited_once_with(ctx.channel, content="🔄 CTF情報を取得中...")
        fetch_mock.assert_awaited_once_with(target_channel=ctx.channel)
        await fake_bot.close()

    async def test_alpacahack_embed_builder(self):
        runtime = self._build_runtime()
        fake_bot = _FakeBot(runtime)
        with patch("discord.ext.tasks.Loop.start", return_value=None):
            cog = Alpacahack(fake_bot)

        summary = WeeklySolveSummary(
            week_start=datetime.date(2026, 3, 2),
            week_end=datetime.date(2026, 3, 8),
            total_users=2,
            weekly_solves={
                "alice": ["web-100", "pwn-200"],
                "bob": ["crypto-100"],
            },
        )
        embed = cog._build_weekly_summary_embed(summary)
        self.assertEqual(embed.title, "🦙 AlpacaHack 今週の solve")
        self.assertEqual(len(embed.fields), 2)
        await fake_bot.close()


if __name__ == "__main__":
    unittest.main()
