from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from ..features.alpacahack.repository import AlpacaHackUserRepository
from .connection import DatabaseConnectionFactory
from .migrations import apply_migrations


@dataclass(frozen=True, slots=True)
class Database:
    """
    Compatibility facade.

    New code should use:
    - `DatabaseConnectionFactory` for connection handling
    - `apply_migrations` for schema setup
    - `AlpacaHackUserRepository` for persistence logic
    """

    database_path: str

    @property
    def connection_factory(self) -> DatabaseConnectionFactory:
        return DatabaseConnectionFactory(database_path=self.database_path)

    @property
    def alpacahack_users(self) -> AlpacaHackUserRepository:
        return AlpacaHackUserRepository(connection_factory=self.connection_factory)

    @contextmanager
    def connection(self) -> Generator[Any, Any, None]:
        with self.connection_factory.connection() as conn:
            yield conn

    def initialize_database(self) -> None:
        apply_migrations(self.connection_factory)

    def insert_alpacahack_user(self, name: str) -> str:
        return self.alpacahack_users.add_user(name)

    def delete_alpacahack_user(self, name: str) -> str:
        return self.alpacahack_users.delete_user(name)

    def list_alpacahack_usernames(self) -> list[str]:
        return self.alpacahack_users.list_usernames()
