from __future__ import annotations

import sqlite3

from ..errors import RepositoryError
from .connection import DatabaseConnectionFactory

MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS alpacahack_user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ctf_role_campaign (
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
        UNIQUE (guild_id, message_id)
    );
    CREATE INDEX IF NOT EXISTS idx_ctf_role_campaign_message
        ON ctf_role_campaign (guild_id, channel_id, message_id, status);
    CREATE INDEX IF NOT EXISTS idx_ctf_role_campaign_status_end
        ON ctf_role_campaign (status, end_at_unix);
    CREATE INDEX IF NOT EXISTS idx_ctf_role_campaign_guild_status_created
        ON ctf_role_campaign (guild_id, status, created_at_unix);
    """,
    """
    ALTER TABLE ctf_role_campaign
    ADD COLUMN discussion_channel_id INTEGER
    """,
    """
    ALTER TABLE ctf_role_campaign
    ADD COLUMN archive_at_unix INTEGER
    """,
    """
    ALTER TABLE ctf_role_campaign
    ADD COLUMN archived_at_unix INTEGER
    """,
    """
    ALTER TABLE ctf_role_campaign
    ADD COLUMN start_notified_at_unix INTEGER
    """,
)


def apply_migrations(factory: DatabaseConnectionFactory) -> None:
    with factory.connection() as conn:
        current_version = _read_user_version(conn)
        target_version = len(MIGRATIONS)
        if current_version > target_version:
            raise RepositoryError(
                "Database schema version is newer than this application supports."
            )

        for version, statement in enumerate(MIGRATIONS, start=1):
            if version <= current_version:
                continue
            conn.executescript(statement)
            _set_user_version(conn, version)

        conn.commit()


def _read_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    if row is None:
        return 0
    return int(row[0])


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {version}")
