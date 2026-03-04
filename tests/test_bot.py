import importlib
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from bs4 import element

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("BOT_CHANNEL_ID", "0")
os.environ.setdefault("TIMEZONE", "Asia/Tokyo")
os.environ.setdefault("DATABASE_PATH", str(REPO_ROOT / "test-alpaca.db"))

from bot.services.alpacahack_service import (  # noqa: E402
    get_week_range,
    get_weekly_solve_challenges,
    is_leaf,
)
from bot.utils.helpers import chunk_message, format_code_block  # noqa: E402


def _reload_database_module(database_path: str):
    with patch.dict(
        os.environ,
        {
            "DISCORD_TOKEN": "test-token",
            "DATABASE_PATH": database_path,
            "TIMEZONE": "Asia/Tokyo",
        },
        clear=False,
    ):
        sys.modules.pop("bot.config", None)
        sys.modules.pop("bot.db.database", None)
        return importlib.import_module("bot.db.database")


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


class TestAlpacaHackService(unittest.TestCase):
    def test_is_leaf(self):
        parent = element.Tag(name="div")
        parent.append("text")
        self.assertTrue(is_leaf(parent))

        parent.append(element.Tag(name="span"))
        self.assertFalse(is_leaf(parent))

    def test_get_week_range(self):
        start, end = get_week_range(date(2026, 3, 4))
        self.assertEqual(start, date(2026, 3, 2))
        self.assertEqual(end, date(2026, 3, 8))

    def test_get_weekly_solve_challenges_filters_by_current_week(self):
        html = """
        <html>
          <body>
            <p>SOLVED CHALLENGES</p>
            <div>
              <table>
                <tbody>
                  <tr>
                    <td><a>weekly-one</a></td>
                    <td><p>1</p></td>
                    <td><span aria-label="2026-03-03 10:00 UTC"></span></td>
                  </tr>
                  <tr>
                    <td><a>old-one</a></td>
                    <td><p>1</p></td>
                    <td><span aria-label="2026-02-28 23:00 UTC"></span></td>
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
            "bot.services.alpacahack_service.requests.get", return_value=response
        ):
            solves = get_weekly_solve_challenges(
                "alice", reference_date=date(2026, 3, 4)
            )

        self.assertEqual(solves, ["weekly-one"])


class TestDatabase(unittest.TestCase):
    def test_insert_and_delete_user(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "alpaca.db")
            db = _reload_database_module(db_path)

            db.initialize_database()
            added = db.insert_alpacahack_user("alice")
            self.assertIn("added", added)
            self.assertEqual(db.list_alpacahack_usernames(), ["alice"])

            deleted = db.delete_alpacahack_user("alice")
            self.assertEqual(deleted, "Deleted user: alice")
            self.assertEqual(db.list_alpacahack_usernames(), [])

    def test_insert_duplicate_user(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "alpaca.db")
            db = _reload_database_module(db_path)

            db.initialize_database()
            db.insert_alpacahack_user("alice")
            duplicate = db.insert_alpacahack_user("alice")
            self.assertIn("already registered", duplicate)


if __name__ == "__main__":
    unittest.main()
