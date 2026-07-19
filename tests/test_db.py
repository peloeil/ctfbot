import os
import sqlite3
import tempfile
import unittest
from contextlib import suppress
from typing import cast
from unittest import mock

from bot.db import _MIGRATIONS, CURRENT_SCHEMA_VERSION, Database
from bot.errors import ConflictError, RepositoryError
from bot.features.ctf_team.models import (
    ActiveCampaign,
    CampaignStatus,
    ClosedCampaign,
)
from bot.features.sudo.models import SudoGrant


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
            "max_active_per_creator": 5,
        }
        values.update(kwargs)
        return self.db.create_campaign(**values)

    def replace_with_version_three_data(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.executescript(
                """
DROP TABLE ctf_team_campaign;
DROP TABLE sudo_grant;
CREATE TABLE ctf_team_campaign (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    ctf_name TEXT NOT NULL COLLATE NOCASE,
    start_at_unix INTEGER NOT NULL,
    end_at_unix INTEGER,
    status TEXT NOT NULL CHECK (status IN ('active', 'closed')),
    created_by INTEGER NOT NULL,
    created_at_unix INTEGER NOT NULL,
    closed_at_unix INTEGER,
    discussion_channel_id INTEGER,
    archive_at_unix INTEGER,
    archived_at_unix INTEGER,
    start_notified_at_unix INTEGER,
    voice_channel_id INTEGER,
    UNIQUE (guild_id, message_id)
);
CREATE INDEX idx_campaign_guild_message
    ON ctf_team_campaign (guild_id, channel_id, message_id, status);
CREATE INDEX idx_campaign_status_end
    ON ctf_team_campaign (status, end_at_unix);
CREATE INDEX idx_campaign_guild_status
    ON ctf_team_campaign (guild_id, status, created_at_unix);
CREATE UNIQUE INDEX idx_campaign_active_name_unique
    ON ctf_team_campaign (guild_id, ctf_name) WHERE status = 'active';
CREATE TABLE sudo_grant (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    granted_at_unix INTEGER NOT NULL,
    expires_at_unix INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE INDEX idx_sudo_grant_expires ON sudo_grant (expires_at_unix);
INSERT INTO ctf_team_campaign VALUES (
    8, 1, 2, 3, 4, 'Example', 100, NULL, 'closed', 5, 90,
    201, NULL, 300, NULL, NULL, 6
);
INSERT INTO sudo_grant VALUES (1, 7, 9, 110, 220);
PRAGMA user_version = 3;
"""
            )

    def test_schema_initialization(self) -> None:
        with sqlite3.connect(self.path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertIn("alpacahack_user", tables)
        self.assertIn("ctf_team_campaign", tables)
        self.assertIn("audit_log_entry", tables)
        self.assertIn("sudo_grant", tables)
        self.assertIn("idx_campaign_status_end", indexes)
        self.assertIn("idx_campaign_status_created", indexes)
        self.assertIn("idx_campaign_active_name_unique", indexes)
        self.assertIn("idx_audit_log_guild_created", indexes)
        self.assertIn("idx_sudo_grant_expires", indexes)
        self.assertEqual(version, CURRENT_SCHEMA_VERSION)
        Database(self.path)

    def test_unmanaged_database_raises(self) -> None:
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            with sqlite3.connect(path) as conn:
                conn.execute("CREATE TABLE unmanaged (id INTEGER PRIMARY KEY)")
            with self.assertRaises(RepositoryError):
                Database(path)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(path)

    def test_version_mismatch(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA user_version = 99")
        with self.assertRaises(RepositoryError):
            Database(self.path)

    def test_migration_applies_pending_scripts(self) -> None:
        migration = "ALTER TABLE alpacahack_user ADD COLUMN note TEXT"
        next_version = CURRENT_SCHEMA_VERSION + 1
        with (
            mock.patch("bot.db.CURRENT_SCHEMA_VERSION", next_version),
            mock.patch.dict("bot.db._MIGRATIONS", {CURRENT_SCHEMA_VERSION: migration}),
        ):
            Database(self.path)
        with sqlite3.connect(self.path) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(alpacahack_user)")
            }
        self.assertEqual(version, next_version)
        self.assertIn("note", columns)

    def test_migration_missing_path_raises(self) -> None:
        with (
            mock.patch("bot.db.CURRENT_SCHEMA_VERSION", CURRENT_SCHEMA_VERSION + 1),
            self.assertRaises(RepositoryError),
        ):
            Database(self.path)

    def test_migration_from_version_one_adds_audit_log_schema(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("DROP TABLE audit_log_entry")
            conn.execute("PRAGMA user_version = 1")
        Database(self.path)
        with sqlite3.connect(self.path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertIn("audit_log_entry", tables)
        self.assertIn("idx_audit_log_guild_created", indexes)
        self.assertEqual(version, CURRENT_SCHEMA_VERSION)

    def test_migration_from_version_two_adds_sudo_schema(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute("DROP TABLE sudo_grant")
            conn.execute("PRAGMA user_version = 2")
        Database(self.path)
        with sqlite3.connect(self.path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
        self.assertIn("sudo_grant", tables)
        self.assertIn("idx_sudo_grant_expires", indexes)

    def test_migration_from_version_three_preserves_state_without_guild_id(
        self,
    ) -> None:
        self.replace_with_version_three_data()

        Database(self.path)

        with sqlite3.connect(self.path) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            campaign_columns = [
                row[1] for row in conn.execute("PRAGMA table_info(ctf_team_campaign)")
            ]
            sudo_columns = [
                row[1] for row in conn.execute("PRAGMA table_info(sudo_grant)")
            ]
            campaign_row = conn.execute(
                "SELECT id, channel_id, message_id, role_id, ctf_name, "
                "start_at_unix, end_at_unix, status, created_by, created_at_unix, "
                "closed_at_unix, discussion_channel_id, archive_at_unix, "
                "archived_at_unix, start_notified_at_unix, voice_channel_id "
                "FROM ctf_team_campaign"
            ).fetchone()
            sudo_row = conn.execute(
                "SELECT user_id, role_id, granted_at_unix, expires_at_unix "
                "FROM sudo_grant"
            ).fetchone()

        self.assertEqual(version, 4)
        self.assertNotIn("guild_id", campaign_columns)
        self.assertNotIn("guild_id", sudo_columns)
        self.assertEqual(
            campaign_row,
            (
                8,
                2,
                3,
                4,
                "Example",
                100,
                None,
                "closed",
                5,
                90,
                201,
                None,
                300,
                None,
                None,
                6,
            ),
        )
        self.assertEqual(sudo_row, (7, 9, 110, 220))

    def test_version_three_migration_can_be_applied_twice_without_state_change(
        self,
    ) -> None:
        self.replace_with_version_three_data()
        with sqlite3.connect(self.path) as conn:
            conn.executescript(_MIGRATIONS[3])
            first_campaign = conn.execute("SELECT * FROM ctf_team_campaign").fetchall()
            first_sudo = conn.execute("SELECT * FROM sudo_grant").fetchall()
            conn.executescript(_MIGRATIONS[3])
            second_campaign = conn.execute("SELECT * FROM ctf_team_campaign").fetchall()
            second_sudo = conn.execute("SELECT * FROM sudo_grant").fetchall()

        self.assertEqual(second_campaign, first_campaign)
        self.assertEqual(second_sudo, first_sudo)

    def test_alpacahack_users(self) -> None:
        self.assertTrue(self.db.add_alpacahack_user(" zeta "))
        self.assertFalse(self.db.add_alpacahack_user("zeta"))
        self.assertTrue(self.db.add_alpacahack_user("alpha"))
        self.assertEqual(self.db.list_alpacahack_users(), ["alpha", "zeta"])
        self.assertTrue(self.db.delete_alpacahack_user("alpha"))
        self.assertFalse(self.db.delete_alpacahack_user("missing"))

    def test_insert_audit_log_entry_is_idempotent(self) -> None:
        values = {
            "entry_id": 10,
            "guild_id": 20,
            "action": "channel_create",
            "user_id": 30,
            "target_id": 40,
            "reason": "test reason",
            "changes_json": '{"before": {}, "after": {}}',
            "extra_text": "extra",
            "created_at_unix": 50,
        }
        self.assertTrue(self.db.insert_audit_log_entry(**values))
        self.assertFalse(self.db.insert_audit_log_entry(**values))
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT entry_id, guild_id, action, user_id, target_id, reason, "
                "changes_json, extra_text, created_at_unix FROM audit_log_entry"
            ).fetchone()
        self.assertEqual(row, tuple(values.values()))

    def test_insert_audit_log_entry_raises_for_non_entry_id_constraint(self) -> None:
        with self.assertRaises(RepositoryError):
            self.db.insert_audit_log_entry(
                entry_id=10,
                guild_id=20,
                action=cast(str, None),
                user_id=30,
                target_id=40,
                reason=None,
                changes_json='{"before": {}, "after": {}}',
                extra_text=None,
                created_at_unix=50,
            )

    def test_sudo_grant_upsert_preserves_initial_granted_time(self) -> None:
        initial = self.db.upsert_sudo_grant(2, 3, 100, 200)
        renewed = self.db.upsert_sudo_grant(2, 4, 150, 300)

        self.assertEqual(initial, SudoGrant(2, 3, 100, 200))
        self.assertEqual(renewed, SudoGrant(2, 4, 100, 300))
        self.assertEqual(self.db.get_sudo_grant(2), renewed)

    def test_expired_sudo_grants_are_ordered_and_deletable(self) -> None:
        later = self.db.upsert_sudo_grant(2, 3, 100, 300)
        earlier = self.db.upsert_sudo_grant(4, 3, 100, 200)
        self.db.upsert_sudo_grant(5, 3, 100, 400)

        self.assertEqual(self.db.list_expired_sudo_grants(300), [earlier, later])
        self.db.delete_sudo_grant(4)
        self.assertIsNone(self.db.get_sudo_grant(4))

    def test_create_and_find_campaign(self) -> None:
        created = self.create_campaign()
        self.assertEqual(created.status, CampaignStatus.ACTIVE)
        self.assertEqual(created.ctf_name, "Example")
        found = self.db.find_active_campaign_by_message(channel_id=2, message_id=3)
        self.assertEqual(found, created)
        self.assertIsNone(
            self.db.find_active_campaign_by_message(channel_id=2, message_id=999)
        )

    def test_decoder_rejects_active_with_closed_fields(self) -> None:
        c = self.create_campaign()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE ctf_team_campaign SET closed_at_unix=1 WHERE id=?",
                (c.id,),
            )
            conn.commit()
        with self.assertRaises(RepositoryError):
            self.db.find_active_campaign_by_message(channel_id=2, message_id=3)

    def test_decoder_rejects_closed_without_required_fields(self) -> None:
        c = self.create_campaign()
        self.db.close_campaign(c.id, 21, 30)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE ctf_team_campaign SET closed_at_unix=NULL WHERE id=?",
                (c.id,),
            )
            conn.commit()
        with self.assertRaises(RepositoryError):
            self.db.find_closed_campaign_by_name(ctf_name="Example")

    def test_create_campaign_returns_active_type(self) -> None:
        c = self.create_campaign()
        self.assertIsInstance(c, ActiveCampaign)
        self.assertEqual(c.status, CampaignStatus.ACTIVE)

    def test_duplicate_active_name_conflicts(self) -> None:
        self.create_campaign("Example")
        with self.assertRaises(ConflictError):
            self.create_campaign("example", message_id=4)

    def test_active_campaign_limit_is_enforced_on_insert(self) -> None:
        for index in range(5):
            self.create_campaign(f"Example {index}", message_id=index + 1)
        with self.assertRaisesRegex(ConflictError, "limit"):
            self.create_campaign("Overflow", message_id=6)

    def test_close_start_archive_and_lists(self) -> None:
        c = self.create_campaign(start_at_unix=10, end_at_unix=20)
        due_starts = self.db.list_due_starts(10)
        self.assertEqual([x.id for x in due_starts], [c.id])
        self.assertIsInstance(due_starts[0], ActiveCampaign)
        self.assertTrue(self.db.mark_started(c.id, 11))
        self.assertFalse(self.db.mark_started(c.id, 12))
        due_campaigns = self.db.list_due_campaigns(20)
        self.assertEqual([x.id for x in due_campaigns], [c.id])
        self.assertIsInstance(due_campaigns[0], ActiveCampaign)
        self.assertTrue(self.db.close_campaign(c.id, 21, 30))
        self.assertIsNone(
            self.db.find_closed_campaign_by_name(
                ctf_name="Example",
                archived=True,
            )
        )
        due_archives = self.db.list_due_archives(30)
        self.assertEqual([x.id for x in due_archives], [c.id])
        self.assertIsInstance(due_archives[0], ClosedCampaign)
        self.assertTrue(self.db.mark_archived(c.id, 31))
        archived = self.db.find_closed_campaign_by_name(
            ctf_name="Example",
            archived=True,
        )
        self.assertIsNotNone(archived)
        assert archived is not None
        self.assertEqual(archived.id, c.id)

    def test_lifecycle_specific_name_lookups_filter_archived(self) -> None:
        c = self.create_campaign("FilterMe")
        self.assertIsNotNone(
            self.db.find_active_campaign_by_name(
                ctf_name="filterme",
            )
        )
        self.assertTrue(self.db.close_campaign(c.id, 21, 30))
        closed = self.db.find_closed_campaign_by_name(
            ctf_name="FILTERME",
            archived=False,
        )
        self.assertIsNotNone(closed)
        self.assertIsInstance(closed, ClosedCampaign)
        self.assertIsNone(
            self.db.find_closed_campaign_by_name(
                ctf_name="FilterMe",
                archived=True,
            )
        )

    def test_decoder_normalizes_zero_optional_channel_ids(self) -> None:
        c = self.create_campaign()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "UPDATE ctf_team_campaign SET discussion_channel_id=0, "
                "voice_channel_id=0 WHERE id=?",
                (c.id,),
            )
            conn.commit()

        active = self.db.find_active_campaign_by_name(ctf_name="Example")
        self.assertIsNotNone(active)
        assert active is not None
        self.assertIsNone(active.discussion_channel_id)
        self.assertIsNone(active.voice_channel_id)

        self.assertTrue(self.db.close_campaign(c.id, 21, 30))
        closed = self.db.find_closed_campaign_by_name(ctf_name="Example")
        self.assertIsNotNone(closed)
        assert closed is not None
        self.assertIsNone(closed.discussion_channel_id)
        self.assertIsNone(closed.voice_channel_id)

    def test_list_campaigns_filters_status_and_orders_desc(self) -> None:
        active_old = self.create_campaign("Old", message_id=10, created_at_unix=10)
        active_new = self.create_campaign("New", message_id=11, created_at_unix=20)
        closed = self.create_campaign("Closed", message_id=12, created_at_unix=30)
        self.assertTrue(self.db.close_campaign(closed.id, 31, 40))

        active = self.db.list_campaigns(CampaignStatus.ACTIVE)
        self.assertEqual([item.id for item in active], [active_new.id, active_old.id])

        closed_items = self.db.list_campaigns(CampaignStatus.CLOSED)
        self.assertEqual([item.id for item in closed_items], [closed.id])

        all_items = self.db.list_campaigns(None)
        self.assertEqual(
            [item.id for item in all_items],
            [closed.id, active_new.id, active_old.id],
        )


if __name__ == "__main__":
    unittest.main()
