import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.errors import ExternalAPIError  # noqa: E402
from bot.features.ctftime.service import CTFTimeService  # noqa: E402


class TestCTFTimeService(unittest.TestCase):
    def setUp(self):
        self.service = CTFTimeService(
            timezone=ZoneInfo("Asia/Tokyo"),
            user_agent="ctfbot-test/1.0",
            retry_backoff_seconds=0,
            sleep_fn=lambda _seconds: None,
        )

    @patch("bot.features.ctftime.service.requests.get")
    def test_get_upcoming_events_parses_payload(self, mock_get: MagicMock):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "title": "Sample CTF",
                "start": "2026-03-10T12:00:00+00:00",
                "finish": "2026-03-11T12:00:00+00:00",
                "url": "https://ctftime.org/event/1",
            }
        ]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        events = self.service.get_upcoming_events(days=7, limit=5)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Sample CTF")
        self.assertEqual(events[0].ctftime_url, "https://ctftime.org/event/1")

    @patch("bot.features.ctftime.service.logger.exception")
    @patch("bot.features.ctftime.service.requests.get")
    def test_get_upcoming_events_raises_on_http_error(
        self, mock_get: MagicMock, _mock_logger_exception: MagicMock
    ):
        mock_get.side_effect = requests.RequestException("network error")
        with self.assertRaises(ExternalAPIError):
            self.service.get_upcoming_events(days=7, limit=5)


if __name__ == "__main__":
    unittest.main()
