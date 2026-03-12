from __future__ import annotations

import sqlite3

from ..errors import RepositoryError
from .connection import DatabaseConnectionFactory

CURRENT_SCHEMA_VERSION = 7
CURRENT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS alpacahack_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS ctf_team_campaign (
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
CREATE INDEX IF NOT EXISTS idx_ctf_team_campaign_message
    ON ctf_team_campaign (guild_id, channel_id, message_id, status);
CREATE INDEX IF NOT EXISTS idx_ctf_team_campaign_status_end
    ON ctf_team_campaign (status, end_at_unix);
CREATE INDEX IF NOT EXISTS idx_ctf_team_campaign_guild_status_created
    ON ctf_team_campaign (guild_id, status, created_at_unix);
"""
EXPECTED_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "alpacahack_user": (
        "id",
        "name",
    ),
    "ctf_team_campaign": (
        "id",
        "guild_id",
        "channel_id",
        "message_id",
        "role_id",
        "ctf_name",
        "start_at_unix",
        "end_at_unix",
        "status",
        "created_by",
        "created_at_unix",
        "closed_at_unix",
        "discussion_channel_id",
        "archive_at_unix",
        "archived_at_unix",
        "start_notified_at_unix",
        "voice_channel_id",
    ),
}


def ensure_current_schema(factory: DatabaseConnectionFactory) -> None:
    with factory.connection() as conn:
        current_version = _read_user_version(conn)
        if current_version == 0:
            if _has_user_defined_objects(conn):
                raise RepositoryError(
                    "Database schema version is missing or unsupported. "
                    "Use a manual migration script or recreate the database."
                )
            conn.executescript(CURRENT_SCHEMA_SQL)
            _set_user_version(conn, CURRENT_SCHEMA_VERSION)
            conn.commit()
            return

        if current_version != CURRENT_SCHEMA_VERSION:
            raise RepositoryError(
                "Database schema version is unsupported. "
                f"Expected {CURRENT_SCHEMA_VERSION}, found {current_version}."
            )

        _validate_current_schema(conn)


def _has_user_defined_objects(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type IN ('table', 'index', 'trigger', 'view')
          AND name NOT LIKE 'sqlite_%'
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def _validate_current_schema(conn: sqlite3.Connection) -> None:
    for table_name, expected_columns in EXPECTED_TABLE_COLUMNS.items():
        actual_columns = _read_table_columns(conn, table_name)
        if actual_columns != expected_columns:
            raise RepositoryError(
                f"Database schema for {table_name} does not match the current schema."
            )


def _read_table_columns(conn: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    if not rows:
        raise RepositoryError(f"Required table is missing: {table_name}")
    return tuple(str(row[1]) for row in rows)


def _read_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    if row is None:
        return 0
    return int(row[0])


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {version}")
