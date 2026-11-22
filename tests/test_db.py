import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest import mock

from ctfbot.db import CURRENT_SCHEMA_VERSION, Database
from ctfbot.errors import ConflictError, RepositoryError
from ctfbot.features.ctfteam.models import (
    ActiveCampaign,
    CampaignStatus,
    ClosedCampaign,
)
from ctfbot.features.sudo.models import SudoGrant


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = str(Path(tmp.name) / "test.db")
        self.db = Database(self.path)

    def schema_version(self) -> int:
        with sqlite3.connect(self.path) as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]

    def rewind_schema(self, version: int, *statements: str) -> None:
        """Make the file look like a database last opened at `version`."""
        with sqlite3.connect(self.path) as conn:
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {version}")

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
DROP TABLE ctfteam_campaign;
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

    def test_fresh_database_is_at_current_schema_version(self) -> None:
        self.assertEqual(self.schema_version(), CURRENT_SCHEMA_VERSION)

    def test_fresh_database_stores_every_feature(self) -> None:
        stores = {
            "alpacahack_user": lambda: self.db.add_alpacahack_user("a", max_users=1),
            "alpacahack_daily_notification": lambda: (
                self.db.reserve_alpacahack_daily_notification("https://example.test")
            ),
            "campaign": lambda: self.create_campaign(),
            "audit_log": lambda: self.db.insert_audit_log_entry(
                entry_id=1,
                guild_id=2,
                action="x",
                user_id=None,
                target_id=None,
                reason=None,
                changes_json="{}",
                extra_text=None,
                created_at_unix=3,
            ),
            "sudo_grant": lambda: self.db.upsert_sudo_grant(1, 2, 3, 4),
            "tts_voice": lambda: self.db.upsert_tts_voice(1, 3, 100),
            "tts_ban": lambda: self.db.add_tts_ban(1, 100),
            "ai_chat_usage": lambda: self.db.record_ai_chat_request(1, "2026-10"),
        }
        for name, write in stores.items():
            with self.subTest(store=name):
                write()

    def test_reopening_current_schema_keeps_data(self) -> None:
        self.db.add_alpacahack_user("alice", max_users=2)

        reopened = Database(self.path)

        self.assertEqual(reopened.list_alpacahack_users(), ["alice"])
        self.assertEqual(self.schema_version(), CURRENT_SCHEMA_VERSION)

    def test_connection_failure_raises_repository_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(RepositoryError),
        ):
            Database(directory)

    def test_database_without_schema_version_is_rejected_as_unmanaged(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = str(Path(tmp.name) / "unmanaged.db")
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE unmanaged (id INTEGER PRIMARY KEY)")

        with self.assertRaises(RepositoryError):
            Database(path)

    def test_database_newer_than_supported_schema_is_rejected(self) -> None:
        self.rewind_schema(CURRENT_SCHEMA_VERSION + 1)

        with self.assertRaises(RepositoryError):
            Database(self.path)

    def test_migration_applies_pending_scripts(self) -> None:
        migration = "ALTER TABLE alpacahack_user ADD COLUMN note TEXT"
        next_version = CURRENT_SCHEMA_VERSION + 1
        with (
            mock.patch("ctfbot.db.CURRENT_SCHEMA_VERSION", next_version),
            mock.patch.dict(
                "ctfbot.db._MIGRATIONS", {CURRENT_SCHEMA_VERSION: migration}
            ),
        ):
            Database(self.path)
        with sqlite3.connect(self.path) as conn:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(alpacahack_user)")
            }
        self.assertEqual(self.schema_version(), next_version)
        self.assertIn("note", columns)

    def test_migration_without_path_to_current_version_is_rejected(self) -> None:
        with (
            mock.patch("ctfbot.db.CURRENT_SCHEMA_VERSION", CURRENT_SCHEMA_VERSION + 1),
            self.assertRaises(RepositoryError),
        ):
            Database(self.path)

    def test_migration_from_version_one_adds_audit_log_and_keeps_campaigns(
        self,
    ) -> None:
        created = self.create_campaign()
        self.rewind_schema(
            1,
            "DROP TABLE audit_log_entry",
            "ALTER TABLE ctfteam_campaign RENAME TO ctf_team_campaign",
        )

        migrated = Database(self.path)

        self.assertTrue(
            migrated.insert_audit_log_entry(
                entry_id=1,
                guild_id=2,
                action="x",
                user_id=None,
                target_id=None,
                reason=None,
                changes_json="{}",
                extra_text=None,
                created_at_unix=3,
            )
        )
        self.assertEqual(
            migrated.find_active_campaign_by_name(ctf_name="Example"), created
        )
        self.assertEqual(self.schema_version(), CURRENT_SCHEMA_VERSION)

    def test_migration_from_version_two_adds_sudo_grants_and_keeps_campaigns(
        self,
    ) -> None:
        created = self.create_campaign()
        self.rewind_schema(
            2,
            "DROP TABLE sudo_grant",
            "ALTER TABLE ctfteam_campaign RENAME TO ctf_team_campaign",
        )

        migrated = Database(self.path)

        self.assertEqual(migrated.upsert_sudo_grant(7, 9, 110, 220).user_id, 7)
        self.assertEqual(
            migrated.find_active_campaign_by_name(ctf_name="Example"), created
        )

    def test_migration_from_version_three_preserves_state_without_guild_id(
        self,
    ) -> None:
        self.replace_with_version_three_data()

        migrated = Database(self.path)

        self.assertEqual(migrated.get_sudo_grant(7), SudoGrant(7, 9, 110, 220))
        self.assertEqual(
            migrated.find_closed_campaign_by_name(ctf_name="Example"),
            ClosedCampaign(
                id=8,
                channel_id=2,
                message_id=3,
                role_id=4,
                ctf_name="Example",
                start_at_unix=100,
                end_at_unix=None,
                status=CampaignStatus.CLOSED,
                created_by=5,
                created_at_unix=90,
                closed_at_unix=201,
                archive_at_unix=300,
                archived_at_unix=None,
                discussion_channel_id=None,
                voice_channel_id=6,
            ),
        )
        self.assertEqual(self.schema_version(), CURRENT_SCHEMA_VERSION)

    def test_version_three_migration_replay_keeps_state(self) -> None:
        self.replace_with_version_three_data()
        Database(self.path)
        self.rewind_schema(
            3, "ALTER TABLE ctfteam_campaign RENAME TO ctf_team_campaign"
        )

        replayed = Database(self.path)

        self.assertEqual(replayed.get_sudo_grant(7), SudoGrant(7, 9, 110, 220))
        closed = replayed.find_closed_campaign_by_name(ctf_name="Example")
        self.assertIsNotNone(closed)
        assert closed is not None
        self.assertEqual(closed.id, 8)

    def test_migration_from_version_four_renames_table_and_preserves_state(
        self,
    ) -> None:
        created = self.create_campaign()
        self.rewind_schema(
            4, "ALTER TABLE ctfteam_campaign RENAME TO ctf_team_campaign"
        )

        migrated = Database(self.path)

        self.assertEqual(self.schema_version(), CURRENT_SCHEMA_VERSION)
        self.assertEqual(
            migrated.find_active_campaign_by_name(ctf_name="Example"), created
        )

    def test_version_four_migration_replay_keeps_state(self) -> None:
        created = self.create_campaign()
        self.rewind_schema(4)

        replayed = Database(self.path)

        self.assertEqual(
            replayed.find_active_campaign_by_name(ctf_name="Example"), created
        )

    def test_migration_from_version_five_adds_daily_notification_store(self) -> None:
        self.rewind_schema(5, "DROP TABLE alpacahack_daily_notification")

        migrated = Database(self.path)

        self.assertTrue(migrated.reserve_alpacahack_daily_notification("u"))

    def test_version_five_migration_replay_keeps_reservations(self) -> None:
        self.db.reserve_alpacahack_daily_notification("u")
        self.rewind_schema(5)

        replayed = Database(self.path)

        self.assertFalse(replayed.reserve_alpacahack_daily_notification("u"))

    def test_version_six_migration_replay_keeps_campaigns(self) -> None:
        created = self.create_campaign()
        self.rewind_schema(
            6,
            "DROP INDEX idx_campaign_due_start",
            "DROP INDEX idx_campaign_due_archive",
            "DROP INDEX idx_campaign_active_creator",
        )

        migrated = Database(self.path)

        self.assertEqual(migrated.list_due_starts(created.start_at_unix), [created])
        self.assertEqual(migrated.count_active_campaigns_by_creator(7), 1)

    def test_migration_from_version_seven_adds_tts_voice_preference(self) -> None:
        self.rewind_schema(7, "DROP TABLE tts_voice_preference")

        migrated = Database(self.path)
        migrated.upsert_tts_voice(1, 3, 100)

        self.assertEqual(migrated.find_tts_voice(1), 3)
        self.assertEqual(self.schema_version(), CURRENT_SCHEMA_VERSION)

    def test_version_seven_migration_replay_keeps_preferences(self) -> None:
        self.db.upsert_tts_voice(1, 3, 100)
        self.rewind_schema(7)

        self.assertEqual(Database(self.path).find_tts_voice(1), 3)

    def test_migration_from_version_eight_adds_ai_chat_usage(self) -> None:
        self.rewind_schema(8, "DROP TABLE ai_chat_usage")

        migrated = Database(self.path)
        self.assertEqual(migrated.count_ai_chat_requests(1, "2026-10"), 0)
        migrated.record_ai_chat_request(1, "2026-10")

        self.assertEqual(migrated.count_ai_chat_requests(1, "2026-10"), 1)
        self.assertEqual(self.schema_version(), CURRENT_SCHEMA_VERSION)

    def test_version_eight_migration_replay_keeps_usage(self) -> None:
        self.db.record_ai_chat_request(1, "2026-10")
        self.rewind_schema(8)

        self.assertEqual(Database(self.path).count_ai_chat_requests(1, "2026-10"), 1)

    def test_migration_from_version_nine_adds_tts_ban(self) -> None:
        self.rewind_schema(9, "DROP TABLE tts_ban")

        migrated = Database(self.path)
        migrated.add_tts_ban(1, 100)

        self.assertTrue(migrated.is_tts_banned(1))
        self.assertEqual(self.schema_version(), CURRENT_SCHEMA_VERSION)

    def test_version_nine_migration_replay_keeps_bans(self) -> None:
        self.db.add_tts_ban(1, 100)
        self.rewind_schema(9)

        self.assertTrue(Database(self.path).is_tts_banned(1))

    def test_tts_voice_preference_lifecycle(self) -> None:
        self.assertIsNone(self.db.find_tts_voice(1))
        self.db.upsert_tts_voice(1, 3, 100)
        self.db.upsert_tts_voice(1, 8, 200)
        self.assertEqual(self.db.find_tts_voice(1), 8)
        self.assertIsNone(self.db.find_tts_voice(2))
        self.assertTrue(self.db.delete_tts_voice(1))
        self.assertFalse(self.db.delete_tts_voice(1))
        self.assertIsNone(self.db.find_tts_voice(1))

    def test_tts_voice_preference_rejects_negative_speaker_id(self) -> None:
        with self.assertRaises(RepositoryError):
            self.db.upsert_tts_voice(1, -1, 100)

    def test_tts_ban_lifecycle(self) -> None:
        self.assertFalse(self.db.is_tts_banned(1))
        self.assertTrue(self.db.add_tts_ban(1, 100))
        self.assertFalse(self.db.add_tts_ban(1, 200))
        self.assertTrue(self.db.is_tts_banned(1))
        self.assertFalse(self.db.is_tts_banned(2))
        self.assertTrue(self.db.delete_tts_ban(1))
        self.assertFalse(self.db.delete_tts_ban(1))
        self.assertFalse(self.db.is_tts_banned(1))

    def test_ai_chat_usage_counts_requests_per_user_and_period(self) -> None:
        self.assertEqual(self.db.count_ai_chat_requests(1, "2026-10"), 0)
        self.db.record_ai_chat_request(1, "2026-10")
        self.db.record_ai_chat_request(1, "2026-10")
        self.db.record_ai_chat_request(1, "2026-11")
        self.db.record_ai_chat_request(2, "2026-10")
        self.assertEqual(self.db.count_ai_chat_requests(1, "2026-10"), 2)
        self.assertEqual(self.db.count_ai_chat_requests(1, "2026-11"), 1)
        self.assertEqual(self.db.count_ai_chat_requests(2, "2026-10"), 1)
        self.assertEqual(self.db.count_ai_chat_requests(2, "2026-11"), 0)

    def test_add_alpacahack_user_trims_name_and_rejects_duplicate(self) -> None:
        self.assertTrue(self.db.add_alpacahack_user(" zeta ", max_users=2))
        self.assertFalse(self.db.add_alpacahack_user("zeta", max_users=2))
        self.assertEqual(self.db.list_alpacahack_users(), ["zeta"])

    def test_add_alpacahack_user_rejects_blank_name(self) -> None:
        with self.assertRaises(RepositoryError):
            self.db.add_alpacahack_user("   ", max_users=2)

    def test_alpacahack_users_are_listed_in_name_order(self) -> None:
        self.db.add_alpacahack_user("zeta", max_users=2)
        self.db.add_alpacahack_user("alpha", max_users=2)

        self.assertEqual(self.db.list_alpacahack_users(), ["alpha", "zeta"])

    def test_delete_alpacahack_user_reports_whether_user_was_registered(self) -> None:
        self.db.add_alpacahack_user("alpha", max_users=2)

        self.assertTrue(self.db.delete_alpacahack_user(" alpha "))
        self.assertEqual(self.db.list_alpacahack_users(), [])
        self.assertFalse(self.db.delete_alpacahack_user("alpha"))

    def test_alpacahack_user_limit_rejects_new_user(self) -> None:
        self.db.add_alpacahack_user("alice", max_users=2)
        self.db.add_alpacahack_user("bob", max_users=2)

        with self.assertRaises(ConflictError):
            self.db.add_alpacahack_user("charlie", max_users=2)
        self.assertEqual(self.db.list_alpacahack_users(), ["alice", "bob"])

    def test_alpacahack_user_limit_does_not_block_registered_user(self) -> None:
        self.db.add_alpacahack_user("alice", max_users=1)

        self.assertFalse(self.db.add_alpacahack_user("alice", max_users=1))

    def test_alpacahack_daily_notification_is_reserved_once_per_url(self) -> None:
        url = "https://alpacahack.com/daily/challenges/example"

        self.assertTrue(self.db.reserve_alpacahack_daily_notification(url))
        self.assertFalse(self.db.reserve_alpacahack_daily_notification(url))

    def test_alpacahack_daily_notification_reserves_each_url_separately(self) -> None:
        self.db.reserve_alpacahack_daily_notification("https://example.test/a")

        self.assertTrue(
            self.db.reserve_alpacahack_daily_notification("https://example.test/b")
        )

    def audit_entry(self, **overrides) -> dict:
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
        values.update(overrides)
        return values

    def test_insert_audit_log_entry_stores_all_fields(self) -> None:
        values = self.audit_entry()

        self.assertTrue(self.db.insert_audit_log_entry(**values))

        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT entry_id, guild_id, action, user_id, target_id, reason, "
                "changes_json, extra_text, created_at_unix FROM audit_log_entry"
            ).fetchone()
        self.assertEqual(row, tuple(values.values()))

    def test_insert_audit_log_entry_ignores_duplicate_entry_id(self) -> None:
        self.assertTrue(self.db.insert_audit_log_entry(**self.audit_entry()))

        self.assertFalse(
            self.db.insert_audit_log_entry(**self.audit_entry(reason="changed"))
        )

        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT reason FROM audit_log_entry").fetchall()
        self.assertEqual(rows, [("test reason",)])

    def test_insert_audit_log_entry_with_null_action_raises_repository_error(
        self,
    ) -> None:
        with self.assertRaises(RepositoryError):
            self.db.insert_audit_log_entry(**self.audit_entry(action=cast(str, None)))

    def test_sudo_grant_upsert_preserves_initial_granted_time(self) -> None:
        initial = self.db.upsert_sudo_grant(2, 3, 100, 200)
        renewed = self.db.upsert_sudo_grant(2, 4, 150, 300)

        self.assertEqual(initial, SudoGrant(2, 3, 100, 200))
        self.assertEqual(renewed, SudoGrant(2, 4, 100, 300))
        self.assertEqual(self.db.get_sudo_grant(2), renewed)

    def test_sudo_grant_is_absent_for_unknown_user(self) -> None:
        self.assertIsNone(self.db.get_sudo_grant(2))

    def test_sudo_grant_is_not_expired_before_expiry_time(self) -> None:
        self.db.upsert_sudo_grant(2, 3, 100, 300)

        self.assertEqual(self.db.list_expired_sudo_grants(299), [])

    def test_sudo_grant_is_expired_at_expiry_time(self) -> None:
        grant = self.db.upsert_sudo_grant(2, 3, 100, 300)

        self.assertEqual(self.db.list_expired_sudo_grants(300), [grant])

    def test_expired_sudo_grants_are_ordered_by_expiry(self) -> None:
        later = self.db.upsert_sudo_grant(2, 3, 100, 300)
        earlier = self.db.upsert_sudo_grant(4, 3, 100, 200)
        self.db.upsert_sudo_grant(5, 3, 100, 400)

        self.assertEqual(self.db.list_expired_sudo_grants(300), [earlier, later])

    def test_delete_sudo_grant_removes_only_that_user(self) -> None:
        kept = self.db.upsert_sudo_grant(2, 3, 100, 300)
        self.db.upsert_sudo_grant(4, 3, 100, 200)

        self.db.delete_sudo_grant(4)

        self.assertIsNone(self.db.get_sudo_grant(4))
        self.assertEqual(self.db.get_sudo_grant(2), kept)

    def test_create_and_find_campaign(self) -> None:
        created = self.create_campaign()
        self.assertIsInstance(created, ActiveCampaign)
        self.assertEqual(created.status, CampaignStatus.ACTIVE)
        self.assertEqual(created.ctf_name, "Example")
        found = self.db.find_active_campaign_by_message(channel_id=2, message_id=3)
        self.assertEqual(found, created)
        self.assertIsNone(
            self.db.find_active_campaign_by_message(channel_id=2, message_id=999)
        )

    def corrupt_campaign(self, campaign_id: int, assignment: str) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                f"UPDATE ctfteam_campaign SET {assignment} WHERE id=?",
                (campaign_id,),
            )
            conn.commit()

    def test_decoder_rejects_active_with_closed_fields(self) -> None:
        for message_id, column in enumerate(
            ("closed_at_unix", "archive_at_unix", "archived_at_unix"), start=100
        ):
            with self.subTest(column=column):
                c = self.create_campaign(f"Active {column}", message_id=message_id)
                self.corrupt_campaign(c.id, f"{column}=1")
                with self.assertRaises(RepositoryError):
                    self.db.find_active_campaign_by_name(ctf_name=c.ctf_name)

    def test_decoder_rejects_closed_without_required_fields(self) -> None:
        for message_id, column in enumerate(
            ("closed_at_unix", "archive_at_unix"), start=200
        ):
            with self.subTest(column=column):
                c = self.create_campaign(f"Closed {column}", message_id=message_id)
                self.db.close_campaign(c.id, 21, 30)
                self.corrupt_campaign(c.id, f"{column}=NULL")
                with self.assertRaises(RepositoryError):
                    self.db.find_closed_campaign_by_name(ctf_name=c.ctf_name)

    def test_duplicate_active_name_conflicts_ignoring_case(self) -> None:
        self.create_campaign("Example")
        with self.assertRaises(ConflictError):
            self.create_campaign("example", message_id=4)

    def test_closed_campaign_name_can_be_reused_by_new_campaign(self) -> None:
        old = self.create_campaign("Example")
        self.db.close_campaign(old.id, 21, 30)

        reused = self.create_campaign("Example", message_id=4)

        self.assertEqual(reused.ctf_name, "Example")

    def test_duplicate_message_id_raises_repository_error_not_conflict(self) -> None:
        self.create_campaign("First")
        with self.assertRaises(RepositoryError) as ctx:
            self.create_campaign("Second")
        self.assertNotIsInstance(ctx.exception, ConflictError)

    def test_active_campaign_limit_is_enforced_on_insert(self) -> None:
        for index in range(2):
            self.create_campaign(
                f"Example {index}", message_id=index + 1, max_active_per_creator=2
            )
        with self.assertRaises(ConflictError):
            self.create_campaign("Overflow", message_id=6, max_active_per_creator=2)

    def test_active_campaign_limit_is_per_creator(self) -> None:
        self.create_campaign("Mine", message_id=1, max_active_per_creator=1)

        other = self.create_campaign(
            "Theirs", message_id=2, created_by=8, max_active_per_creator=1
        )

        self.assertEqual(other.created_by, 8)

    def test_closing_campaign_frees_active_campaign_limit(self) -> None:
        first = self.create_campaign("First", message_id=1, max_active_per_creator=1)
        self.db.close_campaign(first.id, 21, 30)

        second = self.create_campaign("Second", message_id=2, max_active_per_creator=1)

        self.assertEqual(second.ctf_name, "Second")

    def test_count_active_campaigns_by_creator_counts_only_their_active_ones(
        self,
    ) -> None:
        self.create_campaign("A", message_id=1)
        closed = self.create_campaign("B", message_id=2)
        self.create_campaign("C", message_id=3, created_by=8)
        self.db.close_campaign(closed.id, 21, 30)

        self.assertEqual(self.db.count_active_campaigns_by_creator(7), 1)
        self.assertEqual(self.db.count_active_campaigns_by_creator(8), 1)
        self.assertEqual(self.db.count_active_campaigns_by_creator(9), 0)

    def test_has_active_campaign_with_name_ignores_case(self) -> None:
        self.create_campaign("Example")

        self.assertTrue(self.db.has_active_campaign_with_name("example"))
        self.assertFalse(self.db.has_active_campaign_with_name("Other"))

    def test_has_active_campaign_with_name_is_false_after_close(self) -> None:
        c = self.create_campaign("Example")
        self.db.close_campaign(c.id, 21, 30)

        self.assertFalse(self.db.has_active_campaign_with_name("Example"))

    def test_campaign_is_not_due_to_start_before_start_time(self) -> None:
        self.create_campaign(start_at_unix=10)

        self.assertEqual(self.db.list_due_starts(9), [])

    def test_campaign_is_due_to_start_at_start_time(self) -> None:
        c = self.create_campaign(start_at_unix=10)

        self.assertEqual(self.db.list_due_starts(10), [c])

    def test_started_campaign_is_no_longer_due_to_start(self) -> None:
        c = self.create_campaign(start_at_unix=10)

        self.assertTrue(self.db.mark_started(c.id, 11))

        self.assertEqual(self.db.list_due_starts(10), [])

    def test_mark_started_returns_false_on_second_call(self) -> None:
        c = self.create_campaign(start_at_unix=10)
        self.db.mark_started(c.id, 11)

        self.assertFalse(self.db.mark_started(c.id, 12))

    def test_mark_started_does_not_claim_closed_campaign(self) -> None:
        c = self.create_campaign(start_at_unix=10, end_at_unix=20)
        self.assertTrue(self.db.close_campaign(c.id, 21, 30))
        self.assertFalse(self.db.mark_started(c.id, 22))

    def test_campaign_is_not_due_to_close_before_end_time(self) -> None:
        self.create_campaign(end_at_unix=20)

        self.assertEqual(self.db.list_due_campaigns(19), [])

    def test_campaign_is_due_to_close_at_end_time(self) -> None:
        c = self.create_campaign(end_at_unix=20)

        self.assertEqual(self.db.list_due_campaigns(20), [c])

    def test_campaign_without_end_time_is_never_due_to_close(self) -> None:
        self.create_campaign(end_at_unix=None)

        self.assertEqual(self.db.list_due_campaigns(10**12), [])

    def test_closed_campaign_is_no_longer_due_to_close(self) -> None:
        c = self.create_campaign(end_at_unix=20)

        self.assertTrue(self.db.close_campaign(c.id, 21, 30))

        self.assertEqual(self.db.list_due_campaigns(20), [])

    def test_close_campaign_returns_false_when_already_closed(self) -> None:
        c = self.create_campaign()
        self.db.close_campaign(c.id, 21, 30)

        self.assertFalse(self.db.close_campaign(c.id, 22, 31))

    def close_example(self, archive_at_unix: int = 30) -> ClosedCampaign:
        c = self.create_campaign()
        self.db.close_campaign(c.id, 21, archive_at_unix)
        closed = self.db.find_closed_campaign_by_name(ctf_name="Example")
        assert closed is not None
        return closed

    def test_closed_campaign_is_not_due_to_archive_before_archive_time(self) -> None:
        self.close_example(archive_at_unix=30)

        self.assertEqual(self.db.list_due_archives(29), [])

    def test_closed_campaign_is_due_to_archive_at_archive_time(self) -> None:
        closed = self.close_example(archive_at_unix=30)

        self.assertEqual(self.db.list_due_archives(30), [closed])

    def test_active_campaign_is_never_due_to_archive(self) -> None:
        self.create_campaign()

        self.assertEqual(self.db.list_due_archives(10**12), [])

    def test_archived_campaign_is_no_longer_due_to_archive(self) -> None:
        closed = self.close_example()

        self.assertTrue(self.db.mark_archived(closed.id, 31))

        self.assertEqual(self.db.list_due_archives(30), [])

    def test_mark_archived_returns_false_on_second_call(self) -> None:
        closed = self.close_example()
        self.db.mark_archived(closed.id, 31)

        self.assertFalse(self.db.mark_archived(closed.id, 32))

    def test_archived_campaign_matches_only_archived_lookup(self) -> None:
        closed = self.close_example()
        self.db.mark_archived(closed.id, 31)

        archived = self.db.find_closed_campaign_by_name(
            ctf_name="Example", archived=True
        )

        self.assertIsNotNone(archived)
        assert archived is not None
        self.assertEqual(archived.archived_at_unix, 31)
        self.assertIsNone(
            self.db.find_closed_campaign_by_name(ctf_name="Example", archived=False)
        )

    def test_unarchived_closed_campaign_matches_only_unarchived_lookup(self) -> None:
        closed = self.close_example()

        self.assertEqual(
            self.db.find_closed_campaign_by_name(ctf_name="EXAMPLE", archived=False),
            closed,
        )
        self.assertIsNone(
            self.db.find_closed_campaign_by_name(ctf_name="Example", archived=True)
        )

    def test_find_active_campaign_by_name_ignores_case(self) -> None:
        created = self.create_campaign("FilterMe")

        self.assertEqual(
            self.db.find_active_campaign_by_name(ctf_name="filterme"), created
        )

    def test_find_by_name_does_not_cross_active_and_closed(self) -> None:
        active = self.create_campaign("Open", message_id=1)
        closed = self.create_campaign("Done", message_id=2)
        self.db.close_campaign(closed.id, 21, 30)

        self.assertIsNone(
            self.db.find_closed_campaign_by_name(ctf_name=active.ctf_name)
        )
        self.assertIsNone(self.db.find_active_campaign_by_name(ctf_name="Done"))

    def test_decoder_normalizes_zero_optional_channel_ids(self) -> None:
        c = self.create_campaign()
        self.corrupt_campaign(c.id, "discussion_channel_id=0, voice_channel_id=0")

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
