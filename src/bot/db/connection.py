from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from ..errors import RepositoryError

DEFAULT_SQLITE_TIMEOUT_SECONDS = 10.0
DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 5000
SQLITE_CONNECTION_PRAGMAS: tuple[str, ...] = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    f"PRAGMA busy_timeout = {DEFAULT_SQLITE_BUSY_TIMEOUT_MS}",
)


@dataclass(frozen=True, slots=True)
class DatabaseConnectionFactory:
    database_path: str
    timeout_seconds: float = DEFAULT_SQLITE_TIMEOUT_SECONDS

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection]:
        db_path = Path(self.database_path).expanduser().resolve()
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(db_path), timeout=self.timeout_seconds)
            self._configure_connection(conn)
        except sqlite3.Error as exc:
            if conn is not None:
                conn.close()
            raise RepositoryError(f"Failed to open database: {db_path}") from exc

        try:
            yield conn
        except sqlite3.Error as exc:
            raise RepositoryError("Database operation failed.") from exc
        finally:
            conn.close()

    @staticmethod
    def _configure_connection(conn: sqlite3.Connection) -> None:
        for statement in SQLITE_CONNECTION_PRAGMAS:
            conn.execute(statement)
