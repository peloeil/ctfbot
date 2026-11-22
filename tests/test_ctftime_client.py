import datetime
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import discord
import requests

from ctfbot.errors import ExternalAPIError
from ctfbot.features.ctftime import CTFEvent, CTFTimeClient, CTFTimeNotifications
from ctfbot.runtime import BotRuntime

NOW = datetime.datetime(2026, 1, 5, 9, 30, tzinfo=datetime.UTC)


class FixedNow(datetime.datetime):
    @classmethod
    def now(cls, tz: datetime.tzinfo | None = None) -> FixedNow:
        return cast(FixedNow, NOW.astimezone(tz))


class CTFTimeClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tz = ZoneInfo("Asia/Tokyo")
        self.client = CTFTimeClient(
            timezone=self.tz,
            user_agent="ctfbot-test",
            request_timeout=1,
            max_retries=2,
            retry_backoff=0.1,
        )

    def response(self, payload: object) -> Mock:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response

    @patch("ctfbot.features.ctftime.requests.get")
    def test_fetch_events_converts_json(self, get: Mock) -> None:
        get.return_value = self.response(
            [
                {
                    "title": "Example CTF",
                    "start": "2026-01-01T00:00:00Z",
                    "finish": "2026-01-02T00:00:00Z",
                    "ctftime_url": "https://ctftime.org/event/1",
                }
            ]
        )
        events = self.client.fetch_events(days=14, limit=20)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Example CTF")
        self.assertEqual(events[0].start.tzinfo, self.tz)
        self.assertEqual(events[0].start.hour, 9)
        self.assertEqual(events[0].ctftime_url, "https://ctftime.org/event/1")
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs["headers"]["User-Agent"], "ctfbot-test")

    @patch("ctfbot.features.ctftime.requests.get")
    def test_fetch_events_parses_offset_datetime(self, get: Mock) -> None:
        get.return_value = self.response(
            [
                {
                    "title": "Offset CTF",
                    "start": "2026-01-01T12:00:00+09:00",
                    "finish": "2026-01-01T13:00:00+09:00",
                    "url": "https://example.test",
                }
            ]
        )
        events = self.client.fetch_events(days=1, limit=1)
        self.assertEqual(
            events[0].start, datetime.datetime(2026, 1, 1, 12, tzinfo=self.tz)
        )
        self.assertEqual(events[0].ctftime_url, "https://example.test")

    @patch("ctfbot.features.ctftime.requests.get")
    def test_request_window_and_limit_follow_arguments(self, get: Mock) -> None:
        get.return_value = self.response([])

        with patch("datetime.datetime", FixedNow):
            self.client.fetch_events(days=14, limit=20)

        url = urlparse(get.call_args.args[0])
        self.assertEqual(
            (url.scheme, url.netloc, url.path),
            ("https", "ctftime.org", "/api/v1/events/"),
        )
        start = int(NOW.timestamp())
        self.assertEqual(
            parse_qs(url.query),
            {
                "limit": ["20"],
                "start": [str(start)],
                "finish": [str(start + 14 * 24 * 3600)],
            },
        )
        self.assertEqual(get.call_args.kwargs["timeout"], 1)

    @patch("ctfbot.features.ctftime.time.sleep")
    @patch("ctfbot.features.ctftime.requests.get")
    def test_invalid_payloads_raise_after_retries(self, get: Mock, sleep: Mock) -> None:
        valid = {"start": "2026-01-01T00:00:00Z", "finish": "2026-01-02T00:00:00Z"}
        cases = {
            "not a list": {"events": []},
            "item is not an object": ["Example CTF"],
            "missing start": [{"title": "x", "finish": valid["finish"]}],
            "missing finish": [{"title": "x", "start": valid["start"]}],
            "unparsable start": [{**valid, "start": "yesterday"}],
        }
        for label, payload in cases.items():
            with self.subTest(label):
                get.reset_mock()
                get.return_value = self.response(payload)

                with self.assertRaises(ExternalAPIError):
                    self.client.fetch_events(days=1, limit=1)

                self.assertEqual(get.call_count, 2)

    @patch("ctfbot.features.ctftime.requests.get")
    def test_event_without_title_or_url_uses_defaults(self, get: Mock) -> None:
        get.return_value = self.response(
            [{"start": "2026-01-01T00:00:00Z", "finish": "2026-01-02T00:00:00Z"}]
        )

        (event,) = self.client.fetch_events(days=1, limit=1)

        self.assertEqual((event.title, event.ctftime_url), ("Untitled", ""))

    @patch("ctfbot.features.ctftime.requests.get")
    def test_naive_datetime_is_treated_as_utc(self, get: Mock) -> None:
        get.return_value = self.response(
            [{"start": "2026-01-01T00:00:00", "finish": "2026-01-01T01:00:00"}]
        )

        (event,) = self.client.fetch_events(days=1, limit=1)

        self.assertEqual(event.start.hour, 9)

    @patch("ctfbot.features.ctftime.time.sleep")
    @patch("ctfbot.features.ctftime.requests.get")
    def test_fetch_events_retries_once(self, get: Mock, sleep: Mock) -> None:
        get.side_effect = [
            requests.Timeout("timeout"),
            self.response([]),
        ]
        events = self.client.fetch_events(days=1, limit=1)
        self.assertEqual(events, [])
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(0.1)

    @patch("ctfbot.features.ctftime.time.sleep")
    @patch("ctfbot.features.ctftime.requests.get")
    def test_fetch_events_all_failures_raise(self, get: Mock, sleep: Mock) -> None:
        get.side_effect = requests.ConnectionError("failed")
        with self.assertRaises(ExternalAPIError):
            self.client.fetch_events(days=1, limit=1)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(0.1)


class ManualCheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tz = ZoneInfo("Asia/Tokyo")
        self.start = datetime.datetime(2026, 1, 1, tzinfo=tz)
        self.finish = self.start + datetime.timedelta(hours=1)
        settings = SimpleNamespace(
            tzinfo=tz,
            ctftime_user_agent="ctfbot-test",
            ctftime_notification_time=datetime.time(9, tzinfo=tz),
            ctftime_window_days=7,
            ctftime_event_limit=10,
        )
        bot = SimpleNamespace(
            runtime=BotRuntime(settings=cast(Any, settings), db=mock.Mock())
        )
        # The weekly loop is irrelevant here and would run on the event loop.
        with mock.patch("discord.ext.tasks.Loop.start"):
            self.cog = CTFTimeNotifications(cast(Any, bot))
        self.interaction = mock.Mock(spec=discord.Interaction)
        self.interaction.guild = mock.Mock(spec=discord.Guild)
        self.interaction.response = mock.Mock()
        self.interaction.response.defer = mock.AsyncMock()
        self.interaction.followup = mock.Mock()
        self.interaction.followup.send = mock.AsyncMock()

    async def description_for(self, events: list[CTFEvent]) -> str:
        self.cog.client = mock.Mock()
        self.cog.client.fetch_events.return_value = events

        await cast(Any, self.cog.manual_ctf_check.callback)(self.cog, self.interaction)

        self.cog.client.fetch_events.assert_called_once_with(7, 10)
        embed = self.interaction.followup.send.await_args.kwargs["embed"]
        return embed.description or ""

    async def test_embed_omits_unsafe_and_empty_links(self) -> None:
        events = [
            CTFEvent("Empty", self.start, self.finish, ""),
            CTFEvent("Unsafe", self.start, self.finish, "https://example.test/event)"),
            CTFEvent("Safe", self.start, self.finish, "https://example.test/event"),
        ]

        description = await self.description_for(events)

        self.assertEqual(description.count("🔗 [CTFtime]"), 1)
        self.assertIn("🔗 [CTFtime](https://example.test/event)", description)
        self.assertNotIn("[CTFtime]()", description)
        self.assertNotIn("https://example.test/event))", description)

    async def test_embed_states_when_no_events_are_scheduled(self) -> None:
        description = await self.description_for([])

        self.assertEqual(description, "予定されているイベントはありません。")

    async def test_embed_is_cut_before_discord_description_limit(self) -> None:
        events = [CTFEvent("a" * 200, self.start, self.finish, "") for _ in range(40)]

        description = await self.description_for(events)

        self.assertLessEqual(len(description), 4096)
        self.assertLess(description.count("**" + "a" * 200 + "**"), 40)

    async def test_fetch_failure_is_reported_to_the_user(self) -> None:
        self.cog.client = mock.Mock()
        self.cog.client.fetch_events.side_effect = ExternalAPIError("down")

        with self.assertLogs("ctfbot", level="WARNING"):
            await cast(Any, self.cog.manual_ctf_check.callback)(
                self.cog, self.interaction
            )

        args, _ = self.interaction.followup.send.await_args
        self.assertEqual(args[0], "CTFtime からの取得に失敗しました。")
