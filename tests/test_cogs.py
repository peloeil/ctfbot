import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
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
from bot.features.alpacahack.models import (  # noqa: E402
    SolvedChallenge,
    UserMutationResult,
    UserMutationStatus,
)
from bot.features.alpacahack.usecase import WeeklySolveSummary  # noqa: E402
from bot.features.ctftime.cog import CTFTimeNotifications  # noqa: E402
from bot.features.ctftime.models import CTFEvent  # noqa: E402
from bot.runtime import build_runtime  # noqa: E402


class _FakeBot(commands.Bot):
    def __init__(self, runtime):
        intents = discord.Intents.none()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.runtime = runtime


class CogTests(unittest.IsolatedAsyncioTestCase):
    def _build_runtime(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            timezone = ZoneInfo("Asia/Tokyo")
            settings = Settings(
                discord_token="token",
                bot_channel_id=123,
                bot_status_channel_id=0,
                timezone="Asia/Tokyo",
                tzinfo=timezone,
                log_level="INFO",
                database_path=str(Path(tmpdir) / "ctfbot.db"),
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

        class _FakeTextChannel:
            pass

        interaction = SimpleNamespace(user=object(), channel=_FakeTextChannel())
        with (
            patch("bot.features.ctftime.cog.discord.TextChannel", _FakeTextChannel),
            patch.object(cog, "_can_operate_in_channel", return_value=False),
            patch(
                "bot.features.ctftime.cog.send_interaction_message", new=AsyncMock()
            ) as send_mock,
        ):
            await CTFTimeNotifications.manual_ctf_check.callback(cog, interaction)

        send_mock.assert_awaited_once_with(
            interaction,
            "このチャンネルを閲覧・投稿できるメンバーのみ利用できます。",
            ephemeral=True,
        )
        await fake_bot.close()

    async def test_ctftime_manual_check_fetches_when_allowed(self):
        runtime = self._build_runtime()
        fake_bot = _FakeBot(runtime)
        with patch("discord.ext.tasks.Loop.start", return_value=None):
            cog = CTFTimeNotifications(fake_bot)

        class _FakeTextChannel:
            pass

        interaction = SimpleNamespace(user=object(), channel=_FakeTextChannel())
        with (
            patch("bot.features.ctftime.cog.discord.TextChannel", _FakeTextChannel),
            patch.object(cog, "_can_operate_in_channel", return_value=True),
            patch.object(cog, "send_upcoming_ctfs", new=AsyncMock()) as fetch_mock,
            patch(
                "bot.features.ctftime.cog.send_interaction_message", new=AsyncMock()
            ) as send_mock,
        ):
            await CTFTimeNotifications.manual_ctf_check.callback(cog, interaction)

        send_mock.assert_awaited_once_with(
            interaction,
            "🔄 CTF情報を取得中...",
            ephemeral=False,
        )
        fetch_mock.assert_awaited_once_with(target_channel=interaction.channel)
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
                "alice": [
                    SolvedChallenge(
                        name="web-100",
                        url="https://alpacahack.com/challenges/web-100",
                    ),
                    SolvedChallenge(
                        name="pwn-200",
                        url="https://alpacahack.com/challenges/pwn-200",
                    ),
                ],
                "bob": [
                    SolvedChallenge(
                        name="crypto-100",
                        url="https://alpacahack.com/challenges/crypto-100",
                    )
                ],
            },
            failed_users=[],
        )
        embed = cog._build_weekly_summary_embed(summary)
        self.assertEqual(embed.title, "🦙 AlpacaHack 今週の solve")
        self.assertEqual(len(embed.fields), 2)
        description = embed.description or ""
        self.assertIn("取得失敗 0 人", description)
        value = embed.fields[0].value or ""
        self.assertIn(
            "[web-100](https://alpacahack.com/challenges/web-100)",
            value,
        )
        await fake_bot.close()

    async def test_alpacahack_embed_builder_uses_discord_markdown_escape(self):
        runtime = self._build_runtime()
        fake_bot = _FakeBot(runtime)
        with patch("discord.ext.tasks.Loop.start", return_value=None):
            cog = Alpacahack(fake_bot)

        tricky_name = "__init__"
        summary = WeeklySolveSummary(
            week_start=datetime.date(2026, 3, 2),
            week_end=datetime.date(2026, 3, 8),
            total_users=1,
            weekly_solves={"alice": [SolvedChallenge(name=tricky_name, url=None)]},
            failed_users=[],
        )

        embed = cog._build_weekly_summary_embed(summary)

        escaped_name = discord.utils.escape_markdown(tricky_name, as_needed=True)
        value = embed.fields[0].value or ""
        self.assertIn(f"- {escaped_name}", value)
        await fake_bot.close()

    def test_alpacahack_find_target_channel_in_ctf_category(self):
        target_channel = SimpleNamespace(name="alpacahack")
        ctf_category = SimpleNamespace(
            name="ctf",
            text_channels=[SimpleNamespace(name="general"), target_channel],
        )
        guild = SimpleNamespace(categories=[ctf_category])

        resolved = Alpacahack._find_alpacahack_channel(cast(discord.Guild, guild))

        self.assertIs(resolved, target_channel)

    def test_alpacahack_find_target_channel_ignores_other_categories(self):
        target_channel = SimpleNamespace(name="alpacahack")
        misc_category = SimpleNamespace(name="misc", text_channels=[target_channel])
        guild = SimpleNamespace(categories=[misc_category])

        resolved = Alpacahack._find_alpacahack_channel(cast(discord.Guild, guild))

        self.assertIsNone(resolved)

    async def test_alpacahack_embed_builder_shows_failed_users(self):
        runtime = self._build_runtime()
        fake_bot = _FakeBot(runtime)
        with patch("discord.ext.tasks.Loop.start", return_value=None):
            cog = Alpacahack(fake_bot)

        summary = WeeklySolveSummary(
            week_start=datetime.date(2026, 3, 2),
            week_end=datetime.date(2026, 3, 8),
            total_users=2,
            weekly_solves={
                "alice": [
                    SolvedChallenge(
                        name="web-100",
                        url="https://alpacahack.com/challenges/web-100",
                    )
                ]
            },
            failed_users=["bob"],
        )
        embed = cog._build_weekly_summary_embed(summary)
        description = embed.description or ""
        self.assertIn("取得失敗 1 人", description)
        self.assertEqual(embed.fields[-1].name, "取得失敗ユーザー")
        value = embed.fields[-1].value or ""
        self.assertIn("bob", value)
        await fake_bot.close()

    async def test_ctftime_embed_builder_uses_discord_timestamps(self):
        runtime = self._build_runtime()
        fake_bot = _FakeBot(runtime)
        with patch("discord.ext.tasks.Loop.start", return_value=None):
            cog = CTFTimeNotifications(fake_bot)

        event = CTFEvent(
            title="Example CTF",
            start=datetime.datetime(2026, 3, 14, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
            finish=datetime.datetime(2026, 3, 15, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo")),
            ctftime_url="https://ctftime.org/event/1",
        )

        embed = cog._build_events_embed([event])

        self.assertEqual(len(embed.fields), 1)
        value = embed.fields[0].value or ""
        self.assertIn("<t:", value)
        self.assertIn("(<t:", value)
        self.assertNotIn("Asia/Tokyo", value)
        await fake_bot.close()

    async def test_alpacahack_add_replies_ephemerally_in_japanese(self):
        runtime = self._build_runtime()
        fake_bot = _FakeBot(runtime)
        with patch("discord.ext.tasks.Loop.start", return_value=None):
            cog = Alpacahack(fake_bot)

        interaction = SimpleNamespace()
        result = UserMutationResult(
            status=UserMutationStatus.CREATED,
            normalized_name="alice",
        )
        with (
            patch.object(cog.usecase, "add_user", return_value=result),
            patch(
                "bot.features.alpacahack.cog.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
            patch(
                "bot.features.alpacahack.cog.log_command_history",
                new=AsyncMock(),
            ) as audit_mock,
        ):
            await Alpacahack.alpaca_add.callback(cog, interaction, "alice")

        send_mock.assert_awaited_once_with(
            interaction,
            "`alice` を登録しました。",
            ephemeral=True,
        )
        audit_mock.assert_awaited_once()
        audit_args = audit_mock.await_args
        assert audit_args is not None
        self.assertEqual(audit_args.args[0], cog)
        self.assertEqual(audit_args.args[1], interaction)
        self.assertEqual(audit_args.kwargs["command_name"], "/alpaca add")
        self.assertIn("ユーザー名: alice", audit_args.kwargs["details"])
        await fake_bot.close()

    async def test_alpacahack_add_does_not_audit_when_no_mutation(self):
        runtime = self._build_runtime()
        fake_bot = _FakeBot(runtime)
        with patch("discord.ext.tasks.Loop.start", return_value=None):
            cog = Alpacahack(fake_bot)

        interaction = SimpleNamespace()
        result = UserMutationResult(
            status=UserMutationStatus.ALREADY_EXISTS,
            normalized_name="alice",
        )
        with (
            patch.object(cog.usecase, "add_user", return_value=result),
            patch(
                "bot.features.alpacahack.cog.send_interaction_message",
                new=AsyncMock(),
            ),
            patch(
                "bot.features.alpacahack.cog.log_command_history",
                new=AsyncMock(),
            ) as audit_mock,
        ):
            await Alpacahack.alpaca_add.callback(cog, interaction, "alice")

        audit_mock.assert_not_awaited()
        await fake_bot.close()

    async def test_alpacahack_list_replies_ephemerally_with_header(self):
        runtime = self._build_runtime()
        fake_bot = _FakeBot(runtime)
        with patch("discord.ext.tasks.Loop.start", return_value=None):
            cog = Alpacahack(fake_bot)

        interaction = SimpleNamespace()
        with (
            patch.object(cog.usecase, "list_usernames", return_value=["alice", "bob"]),
            patch(
                "bot.features.alpacahack.cog.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await Alpacahack.alpaca_list.callback(cog, interaction)

        await_args = send_mock.await_args
        assert await_args is not None
        self.assertEqual(await_args.args[0], interaction)
        self.assertIn("登録済みAlpacaHackユーザー", await_args.args[1])
        self.assertIn("- alice", await_args.args[1])
        self.assertIn("- bob", await_args.args[1])
        self.assertTrue(await_args.kwargs["ephemeral"])
        await fake_bot.close()


if __name__ == "__main__":
    unittest.main()
