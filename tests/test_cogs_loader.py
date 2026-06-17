import datetime
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from bot.app import create_bot
from bot.cogs_loader import load_cogs
from bot.config import Settings


def settings_for(database_path: str) -> Settings:
    return Settings(
        discord_token="dummy",
        bot_channel_id=0,
        bot_status_channel_id=0,
        ctf_team_category_id=1,
        ctf_team_archive_category_id=2,
        ctftime_channel_id=0,
        alpacahack_channel_id=0,
        timezone="Asia/Tokyo",
        tzinfo=ZoneInfo("Asia/Tokyo"),
        log_level="CRITICAL",
        database_path=database_path,
        alpacahack_solve_time=datetime.time(23, 0),
        ctftime_notification_time=datetime.time(9, 0),
        ctftime_window_days=14,
        ctftime_event_limit=20,
        ctftime_user_agent="ctfbot-test",
    )


class CogsLoaderTest(unittest.IsolatedAsyncioTestCase):
    async def test_loads_default_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bot = create_bot(settings_for(str(Path(tmp) / "ctfbot.db")))
            try:
                await load_cogs(bot)
                self.assertEqual(
                    sorted(command.name for command in bot.tree.get_commands()),
                    ["alpaca", "ctfteam", "ctftime", "help", "perms", "times"],
                )
            finally:
                for extension in list(bot.extensions):
                    await bot.unload_extension(extension)
                await bot.close()


if __name__ == "__main__":
    unittest.main()
