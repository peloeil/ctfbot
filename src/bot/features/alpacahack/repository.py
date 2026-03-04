from __future__ import annotations

from dataclasses import dataclass

from ...db.connection import DatabaseConnectionFactory


@dataclass(frozen=True, slots=True)
class AlpacaHackUserRepository:
    connection_factory: DatabaseConnectionFactory

    def add_user(self, name: str) -> str:
        normalized = name.strip()
        if not normalized:
            return "ユーザー名が空です。"

        with self.connection_factory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO alpacahack_user (name) VALUES (?)",
                (normalized,),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return f"User '{normalized}' is already registered."
            return f"User '{normalized}' added."

    def delete_user(self, name: str) -> str:
        normalized = name.strip()
        if not normalized:
            return "ユーザー名が空です。"

        with self.connection_factory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM alpacahack_user WHERE name = ?", (normalized,))
            conn.commit()
            if cursor.rowcount == 0:
                return f"No user: {normalized}"
            return f"Deleted user: {normalized}"

    def list_usernames(self) -> list[str]:
        with self.connection_factory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM alpacahack_user ORDER BY name ASC")
            rows = cursor.fetchall()
        return [str(row[0]) for row in rows]
