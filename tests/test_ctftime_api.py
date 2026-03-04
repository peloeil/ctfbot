import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("BOT_CHANNEL_ID", "0")
os.environ.setdefault("TIMEZONE", "Asia/Tokyo")

from bot.services.ctftime_service import get_upcoming_events  # noqa: E402


class TestCTFTimeService(unittest.TestCase):
    @patch("bot.services.ctftime_service.requests.get")
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

        events = get_upcoming_events(days=7, limit=5)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "Sample CTF")
        self.assertEqual(events[0].ctftime_url, "https://ctftime.org/event/1")

    @patch("bot.services.ctftime_service.requests.get")
    def test_get_upcoming_events_returns_empty_on_http_error(self, mock_get: MagicMock):
        mock_get.side_effect = requests.RequestException("network error")
        events = get_upcoming_events(days=7, limit=5)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
