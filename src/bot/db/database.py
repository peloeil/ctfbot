"""
Database utilities for the CTF Discord bot.
Handles database connections and operations.
"""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from ..config import DATABASE_NAME


@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, Any, None]:
    """
    Context manager for database connections.
    Ensures connections are properly closed after use.

    Yields:
        sqlite3.Connection: Database connection object
    """
    conn = sqlite3.connect(DATABASE_NAME)
    try:
        yield conn
    finally:
        conn.close()


def execute_query(query: str, params: tuple = ()) -> None:
    """
    Execute a database query with no return value.

    Args:
        query: SQL query string
        params: Query parameters
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()


def fetch_all(query: str, params: tuple = ()) -> list[tuple]:
    """
    Execute a query and fetch all results.

    Args:
        query: SQL query string
        params: Query parameters

    Returns:
        List of query results
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()


def fetch_one(query: str, params: tuple = ()) -> tuple | None:
    """
    Execute a query and fetch one result.

    Args:
        query: SQL query string
        params: Query parameters

    Returns:
        Single query result or None
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()


# AlpacaHack specific database functions
def create_alpacahack_user_table_if_not_exists() -> None:
    """Create the alpacahack_user table if it doesn't exist."""
    query = """
    CREATE TABLE IF NOT EXISTS alpacahack_user (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    )
    """
    execute_query(query)


def insert_alpacahack_user(name: str) -> str:
    """
    Insert a new user into the alpacahack_user table.

    Args:
        name: Username to insert

    Returns:
        Result message
    """
    try:
        execute_query("INSERT INTO alpacahack_user (name) VALUES (?)", (name,))
        return f"User '{name}' added."
    except sqlite3.IntegrityError as e:
        return f"Insert error: {e}"


def delete_alpacahack_user(name: str) -> str:
    """
    Delete a user from the alpacahack_user table.

    Args:
        name: Username to delete

    Returns:
        Result message
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM alpacahack_user WHERE name=?", (name,))
        if cursor.rowcount == 0:
            return f"No user: {name}"
        else:
            return f"Deleted user: {name}"


def get_all_alpacahack_users() -> list[tuple]:
    """
    Get all users from the alpacahack_user table.

    Returns:
        List of usernames
    """
    return fetch_all("SELECT name FROM alpacahack_user")
