import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..config import settings


@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, Any, None]:
    """Context manager for database connections."""
    db_path = Path(settings.database_path).expanduser().resolve()
    conn = sqlite3.connect(str(db_path))
    try:
        yield conn
    finally:
        conn.close()


def execute_query(query: str, params: tuple = ()) -> None:
    """Execute a query and commit changes."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()


def fetch_all(query: str, params: tuple = ()) -> list[tuple[Any, ...]]:
    """Execute a query and fetch all results."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()


def fetch_one(query: str, params: tuple = ()) -> tuple[Any, ...] | None:
    """Execute a query and fetch one result."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()


def initialize_database() -> None:
    """Ensure all required database tables exist."""
    query = """
    CREATE TABLE IF NOT EXISTS alpacahack_user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    )
    """
    execute_query(query)


def create_alpacahack_user_table_if_not_exists() -> None:
    """Backward-compatible wrapper."""
    initialize_database()


def insert_alpacahack_user(name: str) -> str:
    """Insert a new user into the alpacahack_user table."""
    normalized = name.strip()
    if not normalized:
        return "ユーザー名が空です。"

    try:
        execute_query("INSERT INTO alpacahack_user (name) VALUES (?)", (normalized,))
        return f"User '{normalized}' added."
    except sqlite3.IntegrityError:
        return f"User '{normalized}' is already registered."


def delete_alpacahack_user(name: str) -> str:
    """Delete a user from the alpacahack_user table."""
    normalized = name.strip()
    if not normalized:
        return "ユーザー名が空です。"

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM alpacahack_user WHERE name=?", (normalized,))
        conn.commit()
        if cursor.rowcount == 0:
            return f"No user: {normalized}"
        return f"Deleted user: {normalized}"


def get_all_alpacahack_users() -> list[tuple[str]]:
    """Get all users from the alpacahack_user table."""
    return fetch_all("SELECT name FROM alpacahack_user")


def list_alpacahack_usernames() -> list[str]:
    """Return only usernames as a flat list."""
    return [str(row[0]) for row in get_all_alpacahack_users()]
