import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import element

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("BOT_CHANNEL_ID", "0")
os.environ.setdefault("TIMEZONE", "Asia/Tokyo")
os.environ.setdefault("DATABASE_PATH", str(REPO_ROOT / "test-alpaca.db"))

from bot.services.alpacahack_service import is_leaf  # noqa: E402
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
