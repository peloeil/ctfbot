import sqlite3
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
                database_path="alpaca.db",
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
            db_path = Path(tmpdir) / "alpaca.db"
            factory = DatabaseConnectionFactory(database_path=str(db_path))

            apply_migrations(factory)

            with factory.connection() as conn:
                version_row = conn.execute("PRAGMA user_version").fetchone()
                table_row = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='alpacahack_user'"
                ).fetchone()

            self.assertEqual(version_row[0], len(MIGRATIONS))
            self.assertEqual(table_row[0], "alpacahack_user")

    def test_apply_migrations_rejects_newer_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "alpaca.db"
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
                conn.commit()

            factory = DatabaseConnectionFactory(database_path=str(db_path))
            with self.assertRaises(RepositoryError):
                apply_migrations(factory)


if __name__ == "__main__":
    unittest.main()
