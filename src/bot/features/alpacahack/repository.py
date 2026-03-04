from __future__ import annotations

from dataclasses import dataclass

from ...db.connection import DatabaseConnectionFactory
from .models import UserMutationResult, UserMutationStatus


@dataclass(frozen=True, slots=True)
class AlpacaHackUserRepository:
    connection_factory: DatabaseConnectionFactory

    def add_user(self, name: str) -> UserMutationResult:
        normalized = name.strip()
        if not normalized:
            return UserMutationResult(status=UserMutationStatus.INVALID_NAME)

        with self.connection_factory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO alpacahack_user (name) VALUES (?)",
                (normalized,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return UserMutationResult(
                    status=UserMutationStatus.ALREADY_EXISTS,
                    normalized_name=normalized,
                )
            return UserMutationResult(
                status=UserMutationStatus.CREATED,
                normalized_name=normalized,
            )

    def delete_user(self, name: str) -> UserMutationResult:
        normalized = name.strip()
        if not normalized:
            return UserMutationResult(status=UserMutationStatus.INVALID_NAME)

        with self.connection_factory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM alpacahack_user WHERE name = ?", (normalized,))
            conn.commit()
            if cursor.rowcount == 0:
                return UserMutationResult(
                    status=UserMutationStatus.NOT_FOUND,
                    normalized_name=normalized,
                )
            return UserMutationResult(
                status=UserMutationStatus.DELETED,
                normalized_name=normalized,
            )

    def list_usernames(self) -> list[str]:
        with self.connection_factory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM alpacahack_user ORDER BY name ASC")
            rows = cursor.fetchall()
        return [str(row[0]) for row in rows]
