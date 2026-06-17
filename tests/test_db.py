import os
import sqlite3
import tempfile
import unittest
from contextlib import suppress

from bot.db import CURRENT_SCHEMA_VERSION, Database
from bot.errors import ConflictError, RepositoryError
from bot.features.ctf_team.models import CampaignStatus


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.db = Database(self.path)

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            with suppress(FileNotFoundError):
                os.unlink(self.path + suffix)

    def create_campaign(self, name: str = "Example", **kwargs):
        values = {
            "guild_id": 1,
            "channel_id": 2,
            "message_id": 3,
            "role_id": 4,
            "discussion_channel_id": 5,
            "voice_channel_id": 6,
            "ctf_name": name,
            "start_at_unix": 100,
            "end_at_unix": 200,
            "created_by": 7,
            "created_at_unix": 90,
        }
        values.update(kwargs)
        return self.db.create_campaign(**values)

    def test_schema_initialization(self) -> None:
        with sqlite3.connect(self.path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertIn("alpacahack_user", tables)
        self.assertIn("ctf_team_campaign", tables)
        self.assertEqual(version, CURRENT_SCHEMA_VERSION)
        Database(self.path)

    def test_version_mismatch(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA user_version = 99")
        with self.assertRaises(RepositoryError):
            Database(self.path)

    def test_alpacahack_users(self) -> None:
        self.assertTrue(self.db.add_alpacahack_user(" zeta "))
        self.assertFalse(self.db.add_alpacahack_user("zeta"))
        self.assertTrue(self.db.add_alpacahack_user("alpha"))
        self.assertEqual(self.db.list_alpacahack_users(), ["alpha", "zeta"])
        self.assertTrue(self.db.delete_alpacahack_user("alpha"))
        self.assertFalse(self.db.delete_alpacahack_user("missing"))

    def test_create_and_find_campaign(self) -> None:
        created = self.create_campaign()
        self.assertEqual(created.status, CampaignStatus.ACTIVE)
        self.assertEqual(created.ctf_name, "Example")
        found = self.db.find_active_campaign_by_message(
            guild_id=1, channel_id=2, message_id=3
        )
        self.assertEqual(found, created)
        self.assertIsNone(
            self.db.find_active_campaign_by_message(
                guild_id=1, channel_id=2, message_id=999
            )
        )

    def test_duplicate_active_name_conflicts(self) -> None:
        self.create_campaign("Example")
        with self.assertRaises(ConflictError):
            self.create_campaign("example", message_id=4)

    def test_close_start_archive_and_lists(self) -> None:
        c = self.create_campaign(start_at_unix=10, end_at_unix=20)
        self.assertEqual([x.id for x in self.db.list_due_starts(10)], [c.id])
        self.assertTrue(self.db.mark_started(c.id, 11))
        self.assertFalse(self.db.mark_started(c.id, 12))
        self.assertEqual([x.id for x in self.db.list_due_campaigns(20)], [c.id])
        self.assertTrue(self.db.close_campaign(c.id, 21, 30))
        self.assertIsNone(
            self.db.find_campaign_by_name(
                guild_id=1,
                ctf_name="Example",
                status=CampaignStatus.CLOSED,
                archived=True,
            )
        )
        self.assertEqual([x.id for x in self.db.list_due_archives(30)], [c.id])
        self.assertTrue(self.db.mark_archived(c.id, 31))
        archived = self.db.find_campaign_by_name(
            guild_id=1,
            ctf_name="Example",
            status=CampaignStatus.CLOSED,
            archived=True,
        )
        self.assertIsNotNone(archived)
        assert archived is not None
        self.assertEqual(archived.id, c.id)


if __name__ == "__main__":
    unittest.main()
