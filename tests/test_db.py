import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.db.connection import (  # noqa: E402
    SQLITE_CONNECTION_PRAGMAS,
    DatabaseConnectionFactory,
)
from bot.db.migrations import MIGRATIONS, apply_migrations  # noqa: E402
from bot.errors import RepositoryError  # noqa: E402


class DatabaseConnectionTests(unittest.TestCase):
    def test_connection_factory_sets_timeout_and_pragmas(self) -> None:
        mock_conn = Mock()
        with patch(
            "bot.db.connection.sqlite3.connect", return_value=mock_conn
        ) as connect:
            factory = DatabaseConnectionFactory(
                database_path="ctfbot.db",
                timeout_seconds=12.5,
            )
            with factory.connection() as conn:
                self.assertIs(conn, mock_conn)

        connect.assert_called_once()
        self.assertEqual(connect.call_args.kwargs["timeout"], 12.5)
        mock_conn.execute.assert_has_calls(
            [call(statement) for statement in SQLITE_CONNECTION_PRAGMAS]
        )
        mock_conn.close.assert_called_once()


class DatabaseMigrationTests(unittest.TestCase):
    def test_apply_migrations_sets_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            factory = DatabaseConnectionFactory(database_path=str(db_path))

            apply_migrations(factory)

            with factory.connection() as conn:
                version_row = conn.execute("PRAGMA user_version").fetchone()
                alpaca_table_row = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='alpacahack_user'"
                ).fetchone()
                ctf_team_table_row = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='ctf_team_campaign'"
                ).fetchone()
                legacy_table_row = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='ctf_role_campaign'"
                ).fetchone()

            self.assertEqual(version_row[0], len(MIGRATIONS))
            self.assertEqual(alpaca_table_row[0], "alpacahack_user")
            self.assertEqual(ctf_team_table_row[0], "ctf_team_campaign")
            self.assertIsNone(legacy_table_row)

    def test_manual_migration_script_renames_legacy_ctf_role_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            with sqlite3.connect(str(db_path)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE ctf_role_campaign (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guild_id INTEGER NOT NULL,
                        channel_id INTEGER NOT NULL,
                        message_id INTEGER NOT NULL,
                        role_id INTEGER NOT NULL,
                        ctf_name TEXT NOT NULL,
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
                    CREATE INDEX idx_ctf_role_campaign_message
                        ON ctf_role_campaign (guild_id, channel_id, message_id, status);
                    """
                )
                conn.execute(
                    """
                    INSERT INTO ctf_role_campaign (
                        guild_id,
                        channel_id,
                        message_id,
                        role_id,
                        ctf_name,
                        start_at_unix,
                        end_at_unix,
                        status,
                        created_by,
                        created_at_unix,
                        closed_at_unix,
                        discussion_channel_id,
                        archive_at_unix,
                        archived_at_unix,
                        start_notified_at_unix,
                        voice_channel_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        1,
                        10,
                        20,
                        30,
                        "Legacy CTF",
                        1000,
                        2000,
                        "closed",
                        40,
                        500,
                        600,
                        70,
                        800,
                        None,
                        900,
                        100,
                    ),
                )
                conn.execute("PRAGMA user_version = 7")
                conn.commit()

            script_path = REPO_ROOT / "scripts" / "migrate_ctf_team_db.py"
            completed = subprocess.run(
                [sys.executable, str(script_path), str(db_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            with sqlite3.connect(str(db_path)) as conn:
                migrated_row = conn.execute(
                    "SELECT ctf_name, channel_id, archive_at_unix "
                    "FROM ctf_team_campaign"
                ).fetchone()
                version_row = conn.execute("PRAGMA user_version").fetchone()
                legacy_table_row = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='ctf_role_campaign'"
                ).fetchone()
                index_names = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='index' AND tbl_name='ctf_team_campaign'"
                    ).fetchall()
                }

            self.assertEqual(migrated_row, ("Legacy CTF", 10, 800))
            self.assertEqual(version_row[0], len(MIGRATIONS))
            self.assertIsNone(legacy_table_row)
            self.assertIn("idx_ctf_team_campaign_message", index_names)
            self.assertIn("idx_ctf_team_campaign_status_end", index_names)
            self.assertIn("idx_ctf_team_campaign_guild_status_created", index_names)

    def test_apply_migrations_rejects_newer_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
                conn.commit()

            factory = DatabaseConnectionFactory(database_path=str(db_path))
            with self.assertRaises(RepositoryError):
                apply_migrations(factory)


if __name__ == "__main__":
    unittest.main()
