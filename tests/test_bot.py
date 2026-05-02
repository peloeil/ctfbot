import datetime
import signal
import sys
import tempfile
import unittest
from collections.abc import Callable
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import requests
from discord.ext import commands

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.app import CTFBot, run_bot  # noqa: E402
from bot.application.alpacahack import (  # noqa: E402
    ChallengeRef,
    SolveRecord,
    get_week_range,
    select_weekly_solves,
)
from bot.config import Settings  # noqa: E402
from bot.db.connection import DatabaseConnectionFactory  # noqa: E402
from bot.db.migrations import ensure_current_schema  # noqa: E402
from bot.errors import ExternalAPIError  # noqa: E402
from bot.features.alpacahack.models import (  # noqa: E402
    UserMutationStatus,
)
from bot.features.alpacahack.repository import AlpacaHackUserRepository  # noqa: E402
from bot.features.alpacahack.usecase import (  # noqa: E402
    AlpacaHackUseCase,
)
from bot.integrations.alpacahack_scraper import AlpacaHackClient  # noqa: E402
from bot.utils.helpers import chunk_message, format_code_block  # noqa: E402


class TestHelpers(unittest.TestCase):
    def test_format_code_block(self):
        self.assertEqual(format_code_block("test"), "```\ntest\n```")
        self.assertEqual(format_code_block("x", "python"), "```python\nx\n```")

    def test_chunk_message(self):
        message = "a" * 2000
        chunks = chunk_message(message, 1000)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), 1000)
        self.assertEqual(len(chunks[1]), 1000)


class TestAlpacaHackApplication(unittest.TestCase):
    def test_get_week_range(self):
        start, end = get_week_range(date(2026, 3, 4))
        self.assertEqual(start, date(2026, 3, 2))
        self.assertEqual(end, date(2026, 3, 8))

    def test_select_weekly_solves_filters_by_current_week(self):
        timezone = ZoneInfo("Asia/Tokyo")
        solves = select_weekly_solves(
            [
                SolveRecord(
                    challenge=ChallengeRef(name="weekly-one", url=None),
                    solved_at=datetime.datetime(2026, 3, 3, 19, 0, tzinfo=timezone),
                ),
                SolveRecord(
                    challenge=ChallengeRef(name="old-one", url=None),
                    solved_at=datetime.datetime(2026, 2, 28, 23, 0, tzinfo=timezone),
                ),
                SolveRecord(
                    challenge=ChallengeRef(name="weekly-one", url=None),
                    solved_at=datetime.datetime(2026, 3, 4, 10, 0, tzinfo=timezone),
                ),
            ],
            today=date(2026, 3, 4),
        )

        self.assertEqual([solve.name for solve in solves], ["weekly-one"])


class TestAlpacaHackClient(unittest.TestCase):
    def setUp(self):
        self.client = AlpacaHackClient(timezone=ZoneInfo("Asia/Tokyo"))

    def test_fetch_solve_records_supports_gmt_label(self):
        html = """
        <html>
          <body>
            <p>SOLVED CHALLENGES</p>
            <div>
              <table>
                <tbody>
                  <tr>
                    <td><a href="/challenges/daily-one">daily-one</a></td>
                    <td><p>1</p></td>
                    <td><span aria-label="2026-03-04 19:11 GMT+0"></span></td>
                  </tr>
                  <tr>
                    <td><a href="/challenges/daily-two">daily-two</a></td>
                    <td><p>1</p></td>
                    <td><span aria-label="2026-03-04 19:03:30 GMT+0"></span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </body>
        </html>
        """
        response = Mock()
        response.content = html.encode("utf-8")
        response.raise_for_status.return_value = None

        with patch(
            "bot.integrations.alpacahack_scraper.requests.get",
            return_value=response,
        ):
            records = self.client.fetch_solve_records("test-user")

        self.assertEqual(
            [record.challenge.name for record in records], ["daily-one", "daily-two"]
        )

    def test_fetch_solve_records_includes_challenge_links(self):
        html = """
        <html>
          <body>
            <p>SOLVED CHALLENGES</p>
            <div>
              <table>
                <tbody>
                  <tr>
                    <td><a href="/challenges/web-100">web-100</a></td>
                    <td><p>1</p></td>
                    <td><span aria-label="2026-03-04 19:11 GMT+0"></span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </body>
        </html>
        """
        response = Mock()
        response.content = html.encode("utf-8")
        response.raise_for_status.return_value = None

        with patch(
            "bot.integrations.alpacahack_scraper.requests.get",
            return_value=response,
        ):
            records = self.client.fetch_solve_records("test-user")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].challenge.name, "web-100")
        self.assertEqual(
            records[0].challenge.url,
            "https://alpacahack.com/challenges/web-100",
        )

    def test_fetch_solve_records_raises_on_http_error(self):
        with (
            patch(
                "bot.integrations.alpacahack_scraper.requests.get",
                side_effect=requests.RequestException("network error"),
            ),
            self.assertRaises(ExternalAPIError),
        ):
            self.client.fetch_solve_records("alice")

    def test_fetch_solve_records_ignores_legacy_fallback_markup(self):
        html = """
        <html>
          <body>
            <table>
              <tbody class="MuiTableBody-root">
                <tr>
                  <td><a href="/challenges/legacy-one">legacy-one</a></td>
                  <td><p>1</p></td>
                  <td><span aria-label="2026-03-04 19:11 GMT+0"></span></td>
                </tr>
              </tbody>
            </table>
          </body>
        </html>
        """
        response = Mock()
        response.content = html.encode("utf-8")
        response.raise_for_status.return_value = None

        with patch(
            "bot.integrations.alpacahack_scraper.requests.get",
            return_value=response,
        ):
            records = self.client.fetch_solve_records("legacy-user")

        self.assertEqual(records, [])


class TestDatabaseAndUseCase(unittest.TestCase):
    def setUp(self):
        self.timezone = ZoneInfo("Asia/Tokyo")

    def _build_usecase(
        self,
        *,
        db_path: str,
        client: Mock | None = None,
    ) -> tuple[AlpacaHackUseCase, Mock]:
        connection_factory = DatabaseConnectionFactory(database_path=db_path)
        ensure_current_schema(connection_factory)
        repository = AlpacaHackUserRepository(connection_factory=connection_factory)
        resolved_client = client or Mock(fetch_solve_records=Mock(return_value=[]))
        usecase = AlpacaHackUseCase(
            repository=repository,
            client=resolved_client,
            timezone=self.timezone,
            request_interval_seconds=0,
            sleep_fn=lambda _seconds: None,
        )
        return usecase, resolved_client

    def test_insert_and_delete_user(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            usecase, _client = self._build_usecase(
                db_path=str(Path(tmp_dir) / "ctfbot.db")
            )

            added = usecase.add_user("alice")
            self.assertEqual(added.status, UserMutationStatus.CREATED)
            self.assertEqual(usecase.list_usernames(), ["alice"])

            deleted = usecase.delete_user("alice")
            self.assertEqual(deleted.status, UserMutationStatus.DELETED)
            self.assertEqual(usecase.list_usernames(), [])

    def test_insert_duplicate_user(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            usecase, _client = self._build_usecase(
                db_path=str(Path(tmp_dir) / "ctfbot.db")
            )

            usecase.add_user("alice")
            duplicate = usecase.add_user("alice")
            self.assertEqual(duplicate.status, UserMutationStatus.ALREADY_EXISTS)

    def test_collect_weekly_solve_result_marks_fetch_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            usecase, client = self._build_usecase(
                db_path=str(Path(tmp_dir) / "ctfbot.db"),
                client=Mock(
                    fetch_solve_records=Mock(side_effect=ExternalAPIError("boom"))
                ),
            )

            result = usecase.collect_weekly_solve_result(
                "alice",
                reference_date=date(2026, 3, 4),
            )

        self.assertTrue(result.fetch_failed)
        self.assertEqual(result.challenges, [])
        client.fetch_solve_records.assert_called_once_with("alice")

    def test_collect_weekly_summary_includes_challenge_links(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = Mock(
                fetch_solve_records=Mock(
                    return_value=[
                        SolveRecord(
                            challenge=ChallengeRef(
                                name="web-100",
                                url="https://alpacahack.com/challenges/web-100",
                            ),
                            solved_at=datetime.datetime(
                                2026,
                                3,
                                4,
                                19,
                                11,
                                tzinfo=self.timezone,
                            ),
                        )
                    ]
                )
            )
            usecase, _client = self._build_usecase(
                db_path=str(Path(tmp_dir) / "ctfbot.db"),
                client=client,
            )
            usecase.add_user("alice")

            summary = usecase.collect_weekly_summary(date(2026, 3, 4))

        self.assertEqual(summary.total_users, 1)
        self.assertEqual(len(summary.weekly_solves["alice"]), 1)
        self.assertEqual(summary.weekly_solves["alice"][0].name, "web-100")
        self.assertEqual(
            summary.weekly_solves["alice"][0].url,
            "https://alpacahack.com/challenges/web-100",
        )
        self.assertEqual(summary.failed_users, [])

    def test_collect_weekly_summary_tracks_failed_users(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = Mock(
                fetch_solve_records=Mock(side_effect=ExternalAPIError("boom"))
            )
            usecase, _client = self._build_usecase(
                db_path=str(Path(tmp_dir) / "ctfbot.db"),
                client=client,
            )
            usecase.add_user("alice")

            summary = usecase.collect_weekly_summary(date(2026, 3, 4))

        self.assertEqual(summary.total_users, 1)
        self.assertEqual(summary.weekly_solves, {})
        self.assertEqual(summary.failed_users, ["alice"])


class TestCTFBotStatusNotifications(unittest.IsolatedAsyncioTestCase):
    def _settings(self) -> Settings:
        tz = ZoneInfo("Asia/Tokyo")
        return Settings(
            discord_token="token",
            bot_channel_id=0,
            bot_status_channel_id=12345,
            ctf_team_category_id=123456789012345678,
            ctf_team_archive_category_id=223456789012345678,
            timezone="Asia/Tokyo",
            tzinfo=tz,
            log_level="INFO",
            database_path=":memory:",
            alpacahack_solve_time=datetime.time(23, 0, tzinfo=tz),
            ctftime_notification_time=datetime.time(9, 0, tzinfo=tz),
            ctftime_window_days=14,
            ctftime_event_limit=20,
            ctftime_user_agent="ctfbot-test/1.0",
        )

    def _build_bot(self) -> tuple[CTFBot, Mock, Mock]:
        settings = self._settings()
        runtime = Mock(settings=settings)
        gateway = Mock()
        channel = Mock()
        channel.send = AsyncMock()
        gateway.resolve_messageable_channel = AsyncMock(return_value=channel)
        with patch("bot.app.DiscordGateway", return_value=gateway):
            bot = CTFBot(runtime)
        return bot, gateway, channel

    async def test_on_disconnect_does_not_send_status_message(self):
        bot, gateway, channel = self._build_bot()

        await bot.on_disconnect()

        gateway.resolve_messageable_channel.assert_not_called()
        channel.send.assert_not_awaited()

    async def test_on_ready_after_initial_connect_does_not_send_reconnect_status(self):
        bot, gateway, channel = self._build_bot()
        bot._connection.user = Mock()
        bot._has_announced_ready = True

        await bot.on_disconnect()
        await bot.on_ready()

        gateway.resolve_messageable_channel.assert_not_called()
        channel.send.assert_not_awaited()

    async def test_on_resumed_does_not_send_status_message(self):
        bot, gateway, channel = self._build_bot()

        await bot.on_resumed()

        gateway.resolve_messageable_channel.assert_not_called()
        channel.send.assert_not_awaited()

    async def test_close_sends_disconnecting_message_once(self):
        bot, gateway, channel = self._build_bot()
        bot.mark_shutdown_requested_by_sigint()

        with (
            patch.object(bot, "is_closed", return_value=False),
            patch.object(commands.Bot, "close", new=AsyncMock()) as super_close,
        ):
            await bot.close()

        super_close.assert_awaited_once()
        self.assertTrue(bot._is_closing)
        gateway.resolve_messageable_channel.assert_awaited_once_with(
            bot.settings.bot_status_channel_id
        )
        channel.send.assert_awaited_once()
        self.assertIn("ctfbot disconnecting at", channel.send.await_args.args[0])

    async def test_close_skips_status_message_without_sigint(self):
        bot, gateway, channel = self._build_bot()

        with (
            patch.object(bot, "is_closed", return_value=False),
            patch.object(commands.Bot, "close", new=AsyncMock()) as super_close,
        ):
            await bot.close()

        super_close.assert_awaited_once()
        gateway.resolve_messageable_channel.assert_not_called()
        channel.send.assert_not_awaited()


class TestRunBot(unittest.TestCase):
    def test_run_bot_uses_discord_client_run(self):
        settings = Mock(discord_token="token")
        bot = Mock(settings=settings)
        previous_sigint_handler = Mock()

        with (
            patch("bot.app.signal.getsignal", return_value=previous_sigint_handler),
            patch("bot.app.signal.signal") as signal_fn,
        ):
            run_bot(bot)

        bot.run.assert_called_once_with("token", log_handler=None)
        self.assertEqual(signal_fn.call_count, 2)
        self.assertEqual(
            signal_fn.call_args_list[-1].args,
            (signal.SIGINT, previous_sigint_handler),
        )

    def test_run_bot_sigint_handler_marks_bot_and_chains_previous_handler(self):
        settings = Mock(discord_token="token")
        bot = Mock(settings=settings)
        previous_sigint_handler = Mock()
        installed_handler: Callable[[int, object | None], None] | None = None

        def capture_signal(signum, handler):
            nonlocal installed_handler
            if installed_handler is None:
                installed_handler = handler

        with (
            patch("bot.app.signal.getsignal", return_value=previous_sigint_handler),
            patch("bot.app.signal.signal", side_effect=capture_signal),
        ):
            run_bot(bot)

        assert installed_handler is not None
        installed_handler(signal.SIGINT, None)
        bot.mark_shutdown_requested_by_sigint.assert_called_once_with()
        previous_sigint_handler.assert_called_once_with(signal.SIGINT, None)


if __name__ == "__main__":
    unittest.main()
