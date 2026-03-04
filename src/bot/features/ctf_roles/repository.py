from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from ...db.connection import DatabaseConnectionFactory
from .models import CampaignStatus, CTFRoleCampaign

SELECT_COLUMNS = (
    "id, guild_id, channel_id, message_id, role_id, ctf_name, "
    "start_at_unix, end_at_unix, status, created_by, created_at_unix, closed_at_unix"
)


@dataclass(frozen=True, slots=True)
class CTFRoleCampaignRepository:
    connection_factory: DatabaseConnectionFactory

    def count_active_campaigns_by_creator(self, guild_id: int, created_by: int) -> int:
        with self.connection_factory.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(1)
                FROM ctf_role_campaign
                WHERE guild_id = ? AND created_by = ? AND status = ?
                """,
                (guild_id, created_by, CampaignStatus.ACTIVE.value),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def has_active_campaign_with_name(self, guild_id: int, ctf_name: str) -> bool:
        with self.connection_factory.connection() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM ctf_role_campaign
                WHERE guild_id = ?
                  AND status = ?
                  AND ctf_name = ? COLLATE NOCASE
                LIMIT 1
                """,
                (guild_id, CampaignStatus.ACTIVE.value, ctf_name),
            ).fetchone()
        return row is not None

    def create_campaign(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
        role_id: int,
        ctf_name: str,
        start_at_unix: int,
        end_at_unix: int | None,
        created_by: int,
        created_at_unix: int,
    ) -> CTFRoleCampaign:
        with self.connection_factory.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ctf_role_campaign (
                    guild_id,
                    channel_id,
                    message_id,
                    role_id,
                    ctf_name,
                    start_at_unix,
                    end_at_unix,
                    status,
                    created_by,
                    created_at_unix
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    channel_id,
                    message_id,
                    role_id,
                    ctf_name,
                    start_at_unix,
                    end_at_unix,
                    CampaignStatus.ACTIVE.value,
                    created_by,
                    created_at_unix,
                ),
            )
            conn.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("Failed to resolve inserted campaign id.")
            campaign_id = int(cursor.lastrowid)

        return CTFRoleCampaign(
            id=campaign_id,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
            role_id=role_id,
            ctf_name=ctf_name,
            start_at_unix=start_at_unix,
            end_at_unix=end_at_unix,
            status=CampaignStatus.ACTIVE,
            created_by=created_by,
            created_at_unix=created_at_unix,
            closed_at_unix=None,
        )

    def find_active_campaign_by_message(
        self,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> CTFRoleCampaign | None:
        with self.connection_factory.connection() as conn:
            row = conn.execute(
                f"""
                SELECT {SELECT_COLUMNS}
                FROM ctf_role_campaign
                WHERE guild_id = ?
                  AND channel_id = ?
                  AND message_id = ?
                  AND status = ?
                LIMIT 1
                """,
                (guild_id, channel_id, message_id, CampaignStatus.ACTIVE.value),
            ).fetchone()
        return self._to_campaign(row)

    def find_active_campaign_by_name(
        self, *, guild_id: int, ctf_name: str
    ) -> CTFRoleCampaign | None:
        with self.connection_factory.connection() as conn:
            row = conn.execute(
                f"""
                SELECT {SELECT_COLUMNS}
                FROM ctf_role_campaign
                WHERE guild_id = ?
                  AND status = ?
                  AND ctf_name = ? COLLATE NOCASE
                ORDER BY created_at_unix DESC
                LIMIT 1
                """,
                (guild_id, CampaignStatus.ACTIVE.value, ctf_name),
            ).fetchone()
        return self._to_campaign(row)

    def list_due_campaigns(
        self, *, now_unix: int, limit: int = 20
    ) -> list[CTFRoleCampaign]:
        safe_limit = max(1, min(limit, 100))
        with self.connection_factory.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT {SELECT_COLUMNS}
                FROM ctf_role_campaign
                WHERE status = ?
                  AND end_at_unix IS NOT NULL
                  AND end_at_unix <= ?
                ORDER BY end_at_unix ASC
                LIMIT ?
                """,
                (CampaignStatus.ACTIVE.value, now_unix, safe_limit),
            ).fetchall()
        return [campaign for row in rows if (campaign := self._to_campaign(row))]

    def close_campaign(self, *, campaign_id: int, closed_at_unix: int) -> bool:
        with self.connection_factory.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE ctf_role_campaign
                SET status = ?, closed_at_unix = ?
                WHERE id = ? AND status = ?
                """,
                (
                    CampaignStatus.CLOSED.value,
                    closed_at_unix,
                    campaign_id,
                    CampaignStatus.ACTIVE.value,
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def list_campaigns(
        self,
        *,
        guild_id: int,
        status: CampaignStatus | None,
        limit: int = 20,
    ) -> list[CTFRoleCampaign]:
        safe_limit = max(1, min(limit, 100))
        params: tuple[object, ...]
        query = f"""
            SELECT {SELECT_COLUMNS}
            FROM ctf_role_campaign
            WHERE guild_id = ?
        """
        params = (guild_id,)
        if status is not None:
            query += " AND status = ?"
            params = (guild_id, status.value)
        query += " ORDER BY created_at_unix DESC LIMIT ?"
        params = (*params, safe_limit)

        with self.connection_factory.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [campaign for row in rows if (campaign := self._to_campaign(row))]

    @staticmethod
    def _to_campaign(row: tuple[object, ...] | None) -> CTFRoleCampaign | None:
        if row is None:
            return None

        typed_row = cast(tuple[Any, ...], row)
        status_raw = str(typed_row[8])
        status = (
            CampaignStatus.ACTIVE
            if status_raw == CampaignStatus.ACTIVE.value
            else CampaignStatus.CLOSED
        )

        end_at_unix = (
            int(cast(int, typed_row[7])) if typed_row[7] is not None else None
        )
        closed_at_unix = (
            int(cast(int, typed_row[11])) if typed_row[11] is not None else None
        )

        return CTFRoleCampaign(
            id=int(cast(int, typed_row[0])),
            guild_id=int(cast(int, typed_row[1])),
            channel_id=int(cast(int, typed_row[2])),
            message_id=int(cast(int, typed_row[3])),
            role_id=int(cast(int, typed_row[4])),
            ctf_name=str(typed_row[5]),
            start_at_unix=int(cast(int, typed_row[6])),
            end_at_unix=end_at_unix,
            status=status,
            created_by=int(cast(int, typed_row[9])),
            created_at_unix=int(cast(int, typed_row[10])),
            closed_at_unix=closed_at_unix,
        )
