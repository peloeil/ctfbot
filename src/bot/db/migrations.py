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
