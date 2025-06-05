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


def get_all_alpacahack_users() -> list[tuple[str]]:
    """
    Get all users from the alpacahack_user table.

    Returns:
        List of usernames
    """
    return fetch_all("SELECT name FROM alpacahack_user")


# CTF management specific database functions
def create_ctf_events_table_if_not_exists() -> None:
    """Create the ctf_events table if it doesn't exist."""
    query = """
    CREATE TABLE IF NOT EXISTS ctf_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        guild_id INTEGER NOT NULL,
        role_id INTEGER,
        text_channel_id INTEGER,
        voice_channel_id INTEGER,
        announcement_message_id INTEGER,
        end_time TIMESTAMP,
        is_active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """
    execute_query(query)


def insert_ctf_event(
    name: str,
    guild_id: int,
    role_id: int | None = None,
    text_channel_id: int | None = None,
    voice_channel_id: int | None = None,
    announcement_message_id: int | None = None,
    end_time: str | None = None,
) -> str:
    """
    Insert a new CTF event into the ctf_events table.

    Args:
        name: CTF name
        guild_id: Discord guild ID
        role_id: Discord role ID (optional)
        text_channel_id: Discord text channel ID (optional)
        voice_channel_id: Discord voice channel ID (optional)
        announcement_message_id: Discord announcement message ID (optional)
        end_time: CTF end time in ISO format (optional)

    Returns:
        Result message
    """
    try:
        execute_query(
            """INSERT INTO ctf_events
               (name, guild_id, role_id, text_channel_id, voice_channel_id,
                announcement_message_id, end_time)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                guild_id,
                role_id,
                text_channel_id,
                voice_channel_id,
                announcement_message_id,
                end_time,
            ),
        )
        return f"CTF event '{name}' added."
    except sqlite3.IntegrityError as e:
        return f"Insert error: {e}"


def update_ctf_event(
    name: str,
    guild_id: int,
    role_id: int | None = None,
    text_channel_id: int | None = None,
    voice_channel_id: int | None = None,
    announcement_message_id: int | None = None,
    end_time: str | None = None,
) -> str:
    """
    Update an existing CTF event in the ctf_events table.

    Args:
        name: CTF name
        guild_id: Discord guild ID
        role_id: Discord role ID (optional)
        text_channel_id: Discord text channel ID (optional)
        voice_channel_id: Discord voice channel ID (optional)
        announcement_message_id: Discord announcement message ID (optional)
        end_time: CTF end time in ISO format (optional)

    Returns:
        Result message
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # Build dynamic update query
        update_fields = []
        params = []

        if role_id is not None:
            update_fields.append("role_id = ?")
            params.append(role_id)
        if text_channel_id is not None:
            update_fields.append("text_channel_id = ?")
            params.append(text_channel_id)
        if voice_channel_id is not None:
            update_fields.append("voice_channel_id = ?")
            params.append(voice_channel_id)
        if announcement_message_id is not None:
            update_fields.append("announcement_message_id = ?")
            params.append(announcement_message_id)
        if end_time is not None:
            update_fields.append("end_time = ?")
            params.append(end_time)

        if not update_fields:
            return "No fields to update"

        params.extend([name, guild_id])
        query = f"UPDATE ctf_events SET {', '.join(update_fields)} WHERE name = ? AND guild_id = ?"

        cursor.execute(query, params)
        conn.commit()

        if cursor.rowcount == 0:
            return f"No CTF event found: {name}"
        else:
            return f"Updated CTF event: {name}"


def get_ctf_event(name: str, guild_id: int) -> tuple | None:
    """
    Get a CTF event from the ctf_events table.

    Args:
        name: CTF name
        guild_id: Discord guild ID

    Returns:
        CTF event data or None
    """
    return fetch_one(
        "SELECT * FROM ctf_events WHERE name = ? AND guild_id = ? AND is_active = 1",
        (name, guild_id),
    )


def get_active_ctf_events(guild_id: int) -> list[tuple]:
    """
    Get all active CTF events for a guild.

    Args:
        guild_id: Discord guild ID

    Returns:
        List of active CTF events
    """
    return fetch_all(
        "SELECT * FROM ctf_events WHERE guild_id = ? AND is_active = 1",
        (guild_id,),
    )


def get_ctf_events_to_end() -> list[tuple]:
    """
    Get CTF events that should be ended (past their end time).

    Returns:
        List of CTF events to end
    """
    return fetch_all(
        "SELECT * FROM ctf_events WHERE end_time <= datetime('now') AND is_active = 1"
    )


def deactivate_ctf_event(name: str, guild_id: int) -> str:
    """
    Deactivate a CTF event.

    Args:
        name: CTF name
        guild_id: Discord guild ID

    Returns:
        Result message
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE ctf_events SET is_active = 0 WHERE name = ? AND guild_id = ?",
            (name, guild_id),
        )
        conn.commit()

        if cursor.rowcount == 0:
            return f"No active CTF event found: {name}"
        else:
            return f"Deactivated CTF event: {name}"


def delete_ctf_event(name: str, guild_id: int) -> str:
    """
    Delete a CTF event from the ctf_events table.

    Args:
        name: CTF name
        guild_id: Discord guild ID

    Returns:
        Result message
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM ctf_events WHERE name = ? AND guild_id = ?",
            (name, guild_id),
        )
        conn.commit()

        if cursor.rowcount == 0:
            return f"No CTF event found: {name}"
        else:
            return f"Deleted CTF event: {name}"
