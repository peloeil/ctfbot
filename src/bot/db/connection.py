from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import RepositoryError


@dataclass(frozen=True, slots=True)
class DatabaseConnectionFactory:
    database_path: str

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, Any, None]:
        db_path = Path(self.database_path).expanduser().resolve()
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error as exc:
            raise RepositoryError(f"Failed to open database: {db_path}") from exc

        try:
            yield conn
        except sqlite3.Error as exc:
            raise RepositoryError("Database operation failed.") from exc
        finally:
            conn.close()
