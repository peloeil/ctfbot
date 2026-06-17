import datetime
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests

from bot.errors import ExternalAPIError
from bot.features.ctftime import CTFTimeClient


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

    @patch("bot.features.ctftime.requests.get")
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

    @patch("bot.features.ctftime.requests.get")
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

    @patch("bot.features.ctftime.time.sleep")
    @patch("bot.features.ctftime.requests.get")
    def test_fetch_events_retries_once(self, get: Mock, sleep: Mock) -> None:
        get.side_effect = [
            requests.Timeout("timeout"),
            self.response([]),
        ]
        events = self.client.fetch_events(days=1, limit=1)
        self.assertEqual(events, [])
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(0.1)

    @patch("bot.features.ctftime.time.sleep")
    @patch("bot.features.ctftime.requests.get")
    def test_fetch_events_all_failures_raise(self, get: Mock, sleep: Mock) -> None:
        get.side_effect = requests.ConnectionError("failed")
        with self.assertRaises(ExternalAPIError):
            self.client.fetch_events(days=1, limit=1)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(0.1)


if __name__ == "__main__":
    unittest.main()
