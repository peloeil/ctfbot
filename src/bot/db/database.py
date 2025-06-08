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


from datetime import datetime, timedelta
from typing import Optional


# Sleep records specific database functions
def create_sleep_records_table_if_not_exists() -> None:
    """Create the sleep_records table if it doesn't exist."""
    query = """
    CREATE TABLE IF NOT EXISTS sleep_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date DATE NOT NULL,
        bedtime DATETIME,
        wakeup_time DATETIME,
        sleep_duration INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, date)
    )
    """
    execute_query(query)
    
    # Create index for better performance
    index_query = """
    CREATE INDEX IF NOT EXISTS idx_sleep_records_user_date 
    ON sleep_records(user_id, date)
    """
    execute_query(index_query)


def calculate_sleep_duration(bedtime: str, wakeup_time: str) -> int:
    """
    Calculate sleep duration in minutes between bedtime and wakeup time.
    
    Args:
        bedtime: Bedtime in 'YYYY-MM-DD HH:MM:SS' format
        wakeup_time: Wakeup time in 'YYYY-MM-DD HH:MM:SS' format
    
    Returns:
        Sleep duration in minutes
    """
    bedtime_dt = datetime.fromisoformat(bedtime)
    wakeup_dt = datetime.fromisoformat(wakeup_time)
    
    # If wakeup time is earlier than bedtime, assume it's the next day
    if wakeup_dt < bedtime_dt:
        wakeup_dt += timedelta(days=1)
    
    duration = wakeup_dt - bedtime_dt
    return int(duration.total_seconds() / 60)


def insert_sleep_record(user_id: int, date: str, bedtime: Optional[str] = None, 
                       wakeup_time: Optional[str] = None) -> str:
    """
    Insert or update a sleep record.
    
    Args:
        user_id: Discord user ID
        date: Date in 'YYYY-MM-DD' format
        bedtime: Bedtime in 'YYYY-MM-DD HH:MM:SS' format (optional)
        wakeup_time: Wakeup time in 'YYYY-MM-DD HH:MM:SS' format (optional)
    
    Returns:
        Result message
    """
    try:
        # Check if record exists
        existing = fetch_one(
            "SELECT bedtime, wakeup_time FROM sleep_records WHERE user_id=? AND date=?",
            (user_id, date)
        )
        
        if existing:
            # Update existing record
            current_bedtime, current_wakeup = existing
            new_bedtime = bedtime if bedtime else current_bedtime
            new_wakeup = wakeup_time if wakeup_time else current_wakeup
            
            # Calculate duration if both times are available
            duration = None
            if new_bedtime and new_wakeup:
                duration = calculate_sleep_duration(new_bedtime, new_wakeup)
            
            execute_query(
                """UPDATE sleep_records 
                   SET bedtime=?, wakeup_time=?, sleep_duration=?, updated_at=CURRENT_TIMESTAMP 
                   WHERE user_id=? AND date=?""",
                (new_bedtime, new_wakeup, duration, user_id, date)
            )
            return f"Sleep record updated for {date}"
        else:
            # Insert new record
            duration = None
            if bedtime and wakeup_time:
                duration = calculate_sleep_duration(bedtime, wakeup_time)
            
            execute_query(
                """INSERT INTO sleep_records (user_id, date, bedtime, wakeup_time, sleep_duration) 
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, date, bedtime, wakeup_time, duration)
            )
            return f"Sleep record created for {date}"
            
    except sqlite3.Error as e:
        return f"Database error: {e}"


def get_sleep_record(user_id: int, date: str) -> Optional[tuple]:
    """
    Get sleep record for a specific user and date.
    
    Args:
        user_id: Discord user ID
        date: Date in 'YYYY-MM-DD' format
    
    Returns:
        Tuple of (id, user_id, date, bedtime, wakeup_time, sleep_duration) or None
    """
    return fetch_one(
        """SELECT id, user_id, date, bedtime, wakeup_time, sleep_duration 
           FROM sleep_records WHERE user_id=? AND date=?""",
        (user_id, date)
    )


def get_sleep_records_by_period(user_id: int, start_date: str, end_date: str) -> list[tuple]:
    """
    Get sleep records for a user within a date range.
    
    Args:
        user_id: Discord user ID
        start_date: Start date in 'YYYY-MM-DD' format
        end_date: End date in 'YYYY-MM-DD' format
    
    Returns:
        List of tuples (id, user_id, date, bedtime, wakeup_time, sleep_duration)
    """
    return fetch_all(
        """SELECT id, user_id, date, bedtime, wakeup_time, sleep_duration 
           FROM sleep_records 
           WHERE user_id=? AND date BETWEEN ? AND ? 
           ORDER BY date""",
        (user_id, start_date, end_date)
    )


def delete_sleep_record(user_id: int, date: str) -> str:
    """
    Delete a sleep record for a specific user and date.
    
    Args:
        user_id: Discord user ID
        date: Date in 'YYYY-MM-DD' format
    
    Returns:
        Result message
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sleep_records WHERE user_id=? AND date=?", (user_id, date))
        if cursor.rowcount == 0:
            return f"No sleep record found for {date}"
        else:
            conn.commit()
            return f"Sleep record deleted for {date}"


def get_sleep_statistics(user_id: int, start_date: str, end_date: str) -> dict:
    """
    Calculate sleep statistics for a user within a date range.
    
    Args:
        user_id: Discord user ID
        start_date: Start date in 'YYYY-MM-DD' format
        end_date: End date in 'YYYY-MM-DD' format
    
    Returns:
        Dictionary with sleep statistics
    """
    records = get_sleep_records_by_period(user_id, start_date, end_date)
    
    if not records:
        return {
            "total_records": 0,
            "average_sleep_duration": 0,
            "total_sleep_time": 0,
            "longest_sleep": 0,
            "shortest_sleep": 0
        }
    
    durations = [record[5] for record in records if record[5] is not None]
    
    if not durations:
        return {
            "total_records": len(records),
            "average_sleep_duration": 0,
            "total_sleep_time": 0,
            "longest_sleep": 0,
            "shortest_sleep": 0
        }
    
    return {
        "total_records": len(records),
        "average_sleep_duration": sum(durations) / len(durations),
        "total_sleep_time": sum(durations),
        "longest_sleep": max(durations),
        "shortest_sleep": min(durations)
    }

