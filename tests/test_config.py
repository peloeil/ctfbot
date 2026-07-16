import datetime
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.config import _read_clock_time, load_settings
from bot.errors import ConfigurationError


class ConfigTest(unittest.TestCase):
    def env(self, **overrides: str) -> dict[str, str]:
        base = {
            "DISCORD_TOKEN": "token",
            "CTF_TEAM_CATEGORY_ID": "123",
            "CTF_TEAM_ARCHIVE_CATEGORY_ID": "456",
        }
        base.update(overrides)
        return base

    def test_load_settings_with_required_values(self) -> None:
        settings = load_settings(environ=self.env())
        self.assertEqual(settings.discord_token, "token")
        self.assertEqual(settings.ctf_team_category_id, 123)
        self.assertEqual(settings.ctf_team_archive_category_id, 456)
        self.assertEqual(settings.timezone, "Asia/Tokyo")
        self.assertEqual(settings.tzinfo, ZoneInfo("Asia/Tokyo"))
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.database_path, "ctfbot.db")
        self.assertEqual(
            settings.alpacahack_solve_time, datetime.time(23, 0, tzinfo=settings.tzinfo)
        )
        self.assertEqual(
            settings.ctftime_notification_time,
            datetime.time(9, 0, tzinfo=settings.tzinfo),
        )
        self.assertEqual(settings.ctftime_window_days, 14)
        self.assertEqual(settings.ctftime_event_limit, 20)
        self.assertEqual(settings.ctftime_user_agent, "ctfbot/2.0 (+discord)")
        self.assertIsNone(settings.admin_role_id)
        self.assertIsNone(settings.sudoer_role_id)
        self.assertEqual(settings.sudo_duration_minutes, 30)

    def test_optional_channel_ids_default_to_none(self) -> None:
        defaults = load_settings(environ=self.env())
        explicit_zeroes = load_settings(
            environ=self.env(
                BOT_CHANNEL_ID="0",
                BOT_STATUS_CHANNEL_ID="0",
                CTFTIME_CHANNEL_ID="0",
                ALPACAHACK_CHANNEL_ID="0",
            )
        )
        for settings in (defaults, explicit_zeroes):
            self.assertIsNone(settings.bot_channel_id)
            self.assertIsNone(settings.bot_status_channel_id)
            self.assertIsNone(settings.ctftime_channel_id)
            self.assertIsNone(settings.alpacahack_channel_id)

    def test_optional_channel_ids_accept_positive_values(self) -> None:
        settings = load_settings(
            environ=self.env(
                BOT_CHANNEL_ID="42",
                BOT_STATUS_CHANNEL_ID="43",
                CTFTIME_CHANNEL_ID="44",
                ALPACAHACK_CHANNEL_ID="45",
            )
        )
        self.assertEqual(settings.bot_channel_id, 42)
        self.assertEqual(settings.bot_status_channel_id, 43)
        self.assertEqual(settings.ctftime_channel_id, 44)
        self.assertEqual(settings.alpacahack_channel_id, 45)

    def test_missing_token_raises(self) -> None:
        env = self.env()
        del env["DISCORD_TOKEN"]
        with self.assertRaises(ConfigurationError):
            load_settings(environ=env)

    def test_category_must_be_positive(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_settings(environ=self.env(CTF_TEAM_CATEGORY_ID="0"))
        with self.assertRaises(ConfigurationError):
            load_settings(environ=self.env(CTF_TEAM_ARCHIVE_CATEGORY_ID="0"))

    def test_invalid_timezone_raises(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_settings(environ=self.env(TIMEZONE="No/SuchZone"))

    def test_database_parent_must_exist(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_settings(environ=self.env(DATABASE_PATH="/no/such/parent/ctfbot.db"))

    def test_database_existing_parent_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "ctfbot.db")
            settings = load_settings(environ=self.env(DATABASE_PATH=db_path))
        self.assertEqual(settings.database_path, db_path)

    def test_clock_time_reader(self) -> None:
        tzinfo = ZoneInfo("Asia/Tokyo")
        self.assertEqual(
            _read_clock_time({"RUN_AT": "01:23"}, "RUN_AT", "23:00", tzinfo=tzinfo),
            datetime.time(1, 23, tzinfo=tzinfo),
        )
        self.assertEqual(
            _read_clock_time({}, "RUN_AT", "23:00", tzinfo=tzinfo),
            datetime.time(23, 0, tzinfo=tzinfo),
        )
        with self.assertRaises(ConfigurationError):
            _read_clock_time({"RUN_AT": "25:99"}, "RUN_AT", "23:00", tzinfo=tzinfo)

    def test_positive_numeric_settings(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_settings(environ=self.env(CTFTIME_WINDOW_DAYS="0"))
        with self.assertRaises(ConfigurationError):
            load_settings(environ=self.env(CTFTIME_EVENT_LIMIT="0"))
        with self.assertRaises(ConfigurationError):
            load_settings(environ=self.env(SUDO_DURATION_MINUTES="0"))

    def test_sudo_role_ids_must_be_configured_together(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_settings(environ=self.env(ADMIN_ROLE_ID="10"))
        with self.assertRaises(ConfigurationError):
            load_settings(environ=self.env(SUDOER_ROLE_ID="20"))

        settings = load_settings(
            environ=self.env(
                ADMIN_ROLE_ID="10",
                SUDOER_ROLE_ID="20",
                SUDO_DURATION_MINUTES="45",
            )
        )
        self.assertEqual(settings.admin_role_id, 10)
        self.assertEqual(settings.sudoer_role_id, 20)
        self.assertEqual(settings.sudo_duration_minutes, 45)

    def test_integer_settings_reject_negative_and_non_integer(self) -> None:
        with self.assertRaises(ConfigurationError):
            load_settings(environ=self.env(BOT_CHANNEL_ID="-1"))
        with self.assertRaises(ConfigurationError):
            load_settings(environ=self.env(BOT_CHANNEL_ID="not-an-int"))


if __name__ == "__main__":
    unittest.main()
