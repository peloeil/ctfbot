import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.config import Settings  # noqa: E402
from bot.runtime import build_runtime  # noqa: E402
from bot.runtime_providers import (  # noqa: E402
    build_alpacahack_components,
    build_connection_factory,
    build_ctf_team_components,
    build_ctftime_components,
)


class RuntimeProviderTests(unittest.TestCase):
    def _settings(self, db_path: str) -> Settings:
        tz = ZoneInfo("Asia/Tokyo")
        return Settings(
            discord_token="token",
            bot_channel_id=0,
            bot_status_channel_id=0,
            timezone="Asia/Tokyo",
            tzinfo=tz,
            log_level="INFO",
            database_path=db_path,
            alpacahack_solve_time=datetime.time(23, 0, tzinfo=tz),
            ctftime_notification_time=datetime.time(9, 0, tzinfo=tz),
            ctftime_window_days=14,
            ctftime_event_limit=20,
            ctftime_user_agent="ctfbot-test/1.0",
        )

    def test_build_connection_factory_initializes_current_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = self._settings(str(Path(tmpdir) / "ctfbot.db"))
            factory = build_connection_factory(settings)

            with factory.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='alpacahack_user'"
                )
                row = cursor.fetchone()
            self.assertIsNotNone(row)

    def test_build_runtime_wires_components(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = self._settings(str(Path(tmpdir) / "ctfbot.db"))
            runtime = build_runtime(settings)

            self.assertIs(runtime.settings, settings)
            self.assertIs(
                runtime.alpacahack_usecase._service, runtime.alpacahack_service
            )
            self.assertIs(runtime.ctf_team_usecase._service, runtime.ctf_team_service)
            self.assertIs(runtime.ctftime_usecase._service, runtime.ctftime_service)

    def test_feature_provider_factories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings = self._settings(str(Path(tmpdir) / "ctfbot.db"))
            factory = build_connection_factory(settings)
            alpacahack = build_alpacahack_components(settings, factory)
            ctf_team = build_ctf_team_components(settings, factory)
            ctftime = build_ctftime_components(settings)

            self.assertEqual(alpacahack.usecase.list_usernames(), [])
            self.assertEqual(
                ctf_team.usecase._service.timezone,
                settings.tzinfo,
            )
            self.assertEqual(
                ctftime.usecase._window_days,
                settings.ctftime_window_days,
            )
            self.assertEqual(
                ctftime.usecase._event_limit,
                settings.ctftime_event_limit,
            )


if __name__ == "__main__":
    unittest.main()
