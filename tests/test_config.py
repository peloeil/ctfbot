import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import bot.config  # noqa: E402
from bot.errors import ConfigurationError  # noqa: E402


class SettingsTests(unittest.TestCase):
    @staticmethod
    def _base_env(db_path: str) -> dict[str, str]:
        return {
            "DISCORD_TOKEN": "token",
            "TIMEZONE": "Asia/Tokyo",
            "DATABASE_PATH": db_path,
            "CTF_TEAM_CATEGORY_ID": "123456789012345678",
            "CTF_TEAM_ARCHIVE_CATEGORY_ID": "223456789012345678",
        }

    def test_load_settings_from_explicit_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            env = self._base_env(str(db_path))

            settings = bot.config.load_settings(environ=env)
            self.assertEqual(settings.discord_token, "token")
            self.assertEqual(settings.timezone, "Asia/Tokyo")
            self.assertEqual(settings.database_path, str(db_path))
            self.assertEqual(settings.ctf_team_category_id, 123456789012345678)
            self.assertEqual(
                settings.ctf_team_archive_category_id,
                223456789012345678,
            )
            self.assertEqual(settings.log_level, "INFO")
            self.assertEqual(
                settings.ctftime_notification_time.strftime("%H:%M"),
                "09:00",
            )
            self.assertEqual(
                settings.alpacahack_solve_time.strftime("%H:%M"),
                "23:00",
            )

    def test_default_database_path_is_ctfbot_db(self):
        env = {
            "DISCORD_TOKEN": "token",
            "TIMEZONE": "Asia/Tokyo",
            "CTF_TEAM_CATEGORY_ID": "123456789012345678",
            "CTF_TEAM_ARCHIVE_CATEGORY_ID": "223456789012345678",
        }

        settings = bot.config.load_settings(environ=env)
        self.assertEqual(settings.database_path, "ctfbot.db")

    def test_invalid_timezone_raises_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            env = self._base_env(str(db_path))
            env["TIMEZONE"] = "Invalid/Timezone"

            with self.assertRaises(ConfigurationError):
                bot.config.load_settings(environ=env)

    def test_invalid_clock_time_raises_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            env = self._base_env(str(db_path))
            env["CTFTIME_NOTIFICATION_TIME"] = "99:00"

            with self.assertRaises(ConfigurationError):
                bot.config.load_settings(environ=env)

    def test_negative_bot_channel_id_raises_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            env = self._base_env(str(db_path))
            env["BOT_CHANNEL_ID"] = "-1"

            with self.assertRaises(ConfigurationError):
                bot.config.load_settings(environ=env)

    def test_non_positive_ctftime_window_days_raises_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            env = self._base_env(str(db_path))
            env["CTFTIME_WINDOW_DAYS"] = "0"

            with self.assertRaises(ConfigurationError):
                bot.config.load_settings(environ=env)

    def test_non_positive_ctftime_event_limit_raises_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            env = self._base_env(str(db_path))
            env["CTFTIME_EVENT_LIMIT"] = "-3"

            with self.assertRaises(ConfigurationError):
                bot.config.load_settings(environ=env)

    def test_missing_ctf_team_category_id_raises_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            env = self._base_env(str(db_path))
            env.pop("CTF_TEAM_CATEGORY_ID")

            with self.assertRaises(ConfigurationError):
                bot.config.load_settings(environ=env)

    def test_non_positive_ctf_team_archive_category_id_raises_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            env = self._base_env(str(db_path))
            env["CTF_TEAM_ARCHIVE_CATEGORY_ID"] = "0"

            with self.assertRaises(ConfigurationError):
                bot.config.load_settings(environ=env)


if __name__ == "__main__":
    unittest.main()
