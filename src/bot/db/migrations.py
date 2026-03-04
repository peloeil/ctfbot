from __future__ import annotations

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
        cursor = conn.cursor()
        for statement in MIGRATIONS:
            cursor.execute(statement)
        conn.commit()
