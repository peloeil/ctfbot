import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from bot.errors import ConflictError, RepositoryError
from bot.features.ctf_team.models import (
    ActiveCampaign,
    Campaign,
    CampaignStatus,
    ClosedCampaign,
)
from bot.features.sudo.models import SudoGrant

CURRENT_SCHEMA_VERSION = 4
_MIGRATIONS: dict[int, str] = {
    1: """\
CREATE TABLE IF NOT EXISTS audit_log_entry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL UNIQUE,
    guild_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    user_id INTEGER,
    target_id INTEGER,
    reason TEXT,
    changes_json TEXT NOT NULL,
    extra_text TEXT,
    created_at_unix INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_guild_created
    ON audit_log_entry (guild_id, created_at_unix);
""",
    2: """\
CREATE TABLE IF NOT EXISTS sudo_grant (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    granted_at_unix INTEGER NOT NULL,
    expires_at_unix INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_sudo_grant_expires
    ON sudo_grant (expires_at_unix);
""",
    3: """\
BEGIN;
CREATE TABLE ctf_team_campaign_v4 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    ctf_name TEXT NOT NULL COLLATE NOCASE,
    start_at_unix INTEGER NOT NULL,
    end_at_unix INTEGER,
    status TEXT NOT NULL CHECK (status IN ('active', 'closed')),
    created_by INTEGER NOT NULL,
    created_at_unix INTEGER NOT NULL,
    closed_at_unix INTEGER,
    discussion_channel_id INTEGER,
    archive_at_unix INTEGER,
    archived_at_unix INTEGER,
    start_notified_at_unix INTEGER,
    voice_channel_id INTEGER,
    UNIQUE (message_id)
);
INSERT INTO ctf_team_campaign_v4 (
    id, channel_id, message_id, role_id, ctf_name, start_at_unix, end_at_unix,
    status, created_by, created_at_unix, closed_at_unix, discussion_channel_id,
    archive_at_unix, archived_at_unix, start_notified_at_unix, voice_channel_id
)
SELECT
    id, channel_id, message_id, role_id, ctf_name, start_at_unix, end_at_unix,
    status, created_by, created_at_unix, closed_at_unix, discussion_channel_id,
    archive_at_unix, archived_at_unix, start_notified_at_unix, voice_channel_id
FROM ctf_team_campaign;
DROP TABLE ctf_team_campaign;
ALTER TABLE ctf_team_campaign_v4 RENAME TO ctf_team_campaign;
CREATE TABLE sudo_grant_v4 (
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    granted_at_unix INTEGER NOT NULL,
    expires_at_unix INTEGER NOT NULL,
    PRIMARY KEY (user_id)
);
INSERT INTO sudo_grant_v4 (user_id, role_id, granted_at_unix, expires_at_unix)
SELECT user_id, role_id, granted_at_unix, expires_at_unix FROM sudo_grant;
DROP TABLE sudo_grant;
ALTER TABLE sudo_grant_v4 RENAME TO sudo_grant;
COMMIT;
""",
}

_SCHEMA_DDL = """\
CREATE TABLE IF NOT EXISTS alpacahack_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS ctf_team_campaign (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    ctf_name TEXT NOT NULL COLLATE NOCASE,
    start_at_unix INTEGER NOT NULL,
    end_at_unix INTEGER,
    status TEXT NOT NULL CHECK (status IN ('active', 'closed')),
    created_by INTEGER NOT NULL,
    created_at_unix INTEGER NOT NULL,
    closed_at_unix INTEGER,
    discussion_channel_id INTEGER,
    archive_at_unix INTEGER,
    archived_at_unix INTEGER,
    start_notified_at_unix INTEGER,
    voice_channel_id INTEGER,
    UNIQUE (message_id)
);

CREATE INDEX IF NOT EXISTS idx_campaign_status_end
    ON ctf_team_campaign (status, end_at_unix);
CREATE INDEX IF NOT EXISTS idx_campaign_status_created
    ON ctf_team_campaign (status, created_at_unix);
CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_active_name_unique
    ON ctf_team_campaign (ctf_name)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS audit_log_entry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL UNIQUE,
    guild_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    user_id INTEGER,
    target_id INTEGER,
    reason TEXT,
    changes_json TEXT NOT NULL,
    extra_text TEXT,
    created_at_unix INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_guild_created
    ON audit_log_entry (guild_id, created_at_unix);

CREATE TABLE IF NOT EXISTS sudo_grant (
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    granted_at_unix INTEGER NOT NULL,
    expires_at_unix INTEGER NOT NULL,
    PRIMARY KEY (user_id)
);

CREATE INDEX IF NOT EXISTS idx_sudo_grant_expires
    ON sudo_grant (expires_at_unix);
"""

_CAMPAIGN_COLUMNS = (
    "id, channel_id, message_id, role_id, ctf_name, "
    "start_at_unix, end_at_unix, status, created_by, created_at_unix, "
    "start_notified_at_unix, closed_at_unix, archive_at_unix, archived_at_unix, "
    "discussion_channel_id, voice_channel_id"
)

type _CampaignRow = tuple[
    int,
    int,
    int,
    int,
    str,
    int,
    int | None,
    str,
    int,
    int,
    int | None,
    int | None,
    int | None,
    int | None,
    int | None,
    int | None,
]

type _SudoGrantRow = tuple[int, int, int, int]


class Database:
    def __init__(self, path: str) -> None:
        self._path = str(Path(path).expanduser().resolve())
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection]:
        try:
            conn = sqlite3.connect(self._path, timeout=10.0)
        except sqlite3.Error as exc:
            raise RepositoryError(str(exc)) from exc
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            yield conn
        except sqlite3.Error as exc:
            raise RepositoryError(str(exc)) from exc
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            table_count = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
            if version == 0 and table_count > 0:
                raise RepositoryError("Unmanaged database schema.")
            if version > CURRENT_SCHEMA_VERSION:
                message = (
                    f"Unsupported schema version: {version}; "
                    f"expected {CURRENT_SCHEMA_VERSION}."
                )
                raise RepositoryError(message)
            if version == 0:
                conn.executescript(_SCHEMA_DDL)
                conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
                conn.commit()
                return
            while version < CURRENT_SCHEMA_VERSION:
                script = _MIGRATIONS.get(version)
                if script is None:
                    raise RepositoryError(
                        f"No migration path from schema version {version}."
                    )
                conn.executescript(script)
                version += 1
                conn.execute(f"PRAGMA user_version = {version}")
                conn.commit()
            conn.executescript(_SCHEMA_DDL)
            conn.commit()

    @staticmethod
    def _to_campaign(row: _CampaignRow) -> Campaign:
        try:
            status = CampaignStatus(row[7])
        except ValueError as exc:
            raise RepositoryError(
                f"Campaign {row[0]} has invalid status: {row[7]!r}."
            ) from exc
        if status == CampaignStatus.ACTIVE:
            return Database._to_active_campaign(row)
        return Database._to_closed_campaign(row)

    @staticmethod
    def _to_active_campaign(row: _CampaignRow) -> ActiveCampaign:
        if row[7] != CampaignStatus.ACTIVE.value:
            raise RepositoryError(f"Campaign {row[0]} is not active: {row[7]!r}.")
        if row[11] is not None or row[12] is not None or row[13] is not None:
            raise RepositoryError(
                f"Active campaign {row[0]} has closed/archive fields set."
            )
        return ActiveCampaign(
            id=row[0],
            channel_id=row[1],
            message_id=row[2],
            role_id=row[3],
            ctf_name=row[4],
            start_at_unix=row[5],
            end_at_unix=row[6],
            status=CampaignStatus.ACTIVE,
            created_by=row[8],
            created_at_unix=row[9],
            start_notified_at_unix=row[10],
            discussion_channel_id=row[14] or None,
            voice_channel_id=row[15] or None,
        )

    @staticmethod
    def _to_closed_campaign(row: _CampaignRow) -> ClosedCampaign:
        if row[7] != CampaignStatus.CLOSED.value:
            raise RepositoryError(f"Campaign {row[0]} is not closed: {row[7]!r}.")
        if row[11] is None or row[12] is None:
            raise RepositoryError(
                f"Closed campaign {row[0]} is missing closed_at or archive_at."
            )
        return ClosedCampaign(
            id=row[0],
            channel_id=row[1],
            message_id=row[2],
            role_id=row[3],
            ctf_name=row[4],
            start_at_unix=row[5],
            end_at_unix=row[6],
            status=CampaignStatus.CLOSED,
            created_by=row[8],
            created_at_unix=row[9],
            closed_at_unix=row[11],
            archive_at_unix=row[12],
            archived_at_unix=row[13],
            discussion_channel_id=row[14] or None,
            voice_channel_id=row[15] or None,
        )

    def add_alpacahack_user(self, name: str, *, max_users: int) -> bool:
        clean = name.strip()
        if not clean:
            raise RepositoryError("AlpacaHack username must not be empty.")
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            exists = conn.execute(
                "SELECT 1 FROM alpacahack_user WHERE name = ?", (clean,)
            ).fetchone()
            if exists is not None:
                return False
            count = conn.execute("SELECT COUNT(*) FROM alpacahack_user").fetchone()[0]
            if count >= max_users:
                raise ConflictError("AlpacaHack user limit reached.")
            conn.execute("INSERT INTO alpacahack_user (name) VALUES (?)", (clean,))
            conn.commit()
            return True

    def delete_alpacahack_user(self, name: str) -> bool:
        with self._connection() as conn:
            cur = conn.execute(
                "DELETE FROM alpacahack_user WHERE name = ?", (name.strip(),)
            )
            conn.commit()
            return cur.rowcount > 0

    def list_alpacahack_users(self) -> list[str]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT name FROM alpacahack_user ORDER BY name ASC"
            ).fetchall()
        return [row[0] for row in rows]

    def insert_audit_log_entry(
        self,
        *,
        entry_id: int,
        guild_id: int,
        action: str,
        user_id: int | None,
        target_id: int | None,
        reason: str | None,
        changes_json: str,
        extra_text: str | None,
        created_at_unix: int,
    ) -> bool:
        with self._connection() as conn:
            cur = conn.execute(
                "INSERT INTO audit_log_entry ("
                "entry_id, guild_id, action, user_id, target_id, reason, "
                "changes_json, extra_text, created_at_unix"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (entry_id) DO NOTHING",
                (
                    entry_id,
                    guild_id,
                    action,
                    user_id,
                    target_id,
                    reason,
                    changes_json,
                    extra_text,
                    created_at_unix,
                ),
            )
            conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _to_sudo_grant(row: _SudoGrantRow) -> SudoGrant:
        return SudoGrant(
            user_id=row[0],
            role_id=row[1],
            granted_at_unix=row[2],
            expires_at_unix=row[3],
        )

    def upsert_sudo_grant(
        self,
        user_id: int,
        role_id: int,
        granted_at_unix: int,
        expires_at_unix: int,
    ) -> SudoGrant:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO sudo_grant (user_id, role_id, "
                "granted_at_unix, expires_at_unix) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                "role_id=excluded.role_id, expires_at_unix=excluded.expires_at_unix",
                (user_id, role_id, granted_at_unix, expires_at_unix),
            )
            conn.commit()
            row = conn.execute(
                "SELECT user_id, role_id, granted_at_unix, expires_at_unix "
                "FROM sudo_grant WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return self._to_sudo_grant(row)

    def get_sudo_grant(self, user_id: int) -> SudoGrant | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT user_id, role_id, granted_at_unix, expires_at_unix "
                "FROM sudo_grant WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return self._to_sudo_grant(row) if row else None

    def delete_sudo_grant(self, user_id: int) -> None:
        with self._connection() as conn:
            conn.execute(
                "DELETE FROM sudo_grant WHERE user_id=?",
                (user_id,),
            )
            conn.commit()

    def list_expired_sudo_grants(self, now_unix: int) -> list[SudoGrant]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT user_id, role_id, granted_at_unix, expires_at_unix "
                "FROM sudo_grant WHERE expires_at_unix <= ? "
                "ORDER BY expires_at_unix ASC",
                (now_unix,),
            ).fetchall()
        return [self._to_sudo_grant(row) for row in rows]

    def count_active_campaigns_by_creator(self, created_by: int) -> int:
        with self._connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM ctf_team_campaign "
                "WHERE created_by=? AND status='active'",
                (created_by,),
            ).fetchone()[0]

    def has_active_campaign_with_name(self, ctf_name: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM ctf_team_campaign "
                "WHERE ctf_name=? AND status='active' LIMIT 1",
                (ctf_name,),
            ).fetchone()
        return row is not None

    def create_campaign(
        self,
        *,
        channel_id: int,
        message_id: int,
        role_id: int,
        discussion_channel_id: int | None,
        voice_channel_id: int | None,
        ctf_name: str,
        start_at_unix: int,
        end_at_unix: int | None,
        created_by: int,
        created_at_unix: int,
        max_active_per_creator: int,
    ) -> ActiveCampaign:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active_count = conn.execute(
                "SELECT COUNT(*) FROM ctf_team_campaign "
                "WHERE created_by=? AND status='active'",
                (created_by,),
            ).fetchone()[0]
            if active_count >= max_active_per_creator:
                raise ConflictError("Active campaign limit reached.")
            try:
                cur = conn.execute(
                    "INSERT INTO ctf_team_campaign ("
                    "channel_id, message_id, role_id, "
                    "discussion_channel_id, voice_channel_id, ctf_name, "
                    "start_at_unix, end_at_unix, status, created_by, created_at_unix"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                    (
                        channel_id,
                        message_id,
                        role_id,
                        discussion_channel_id,
                        voice_channel_id,
                        ctf_name,
                        start_at_unix,
                        end_at_unix,
                        created_by,
                        created_at_unix,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # 同名 active の unique index 違反のみ ConflictError。
                # それ以外の制約違反は _connection が RepositoryError に変換する
                if "ctf_team_campaign.ctf_name" not in str(exc):
                    raise
                raise ConflictError("Active campaign already exists.") from exc
            conn.commit()
            row = conn.execute(
                f"SELECT {_CAMPAIGN_COLUMNS} FROM ctf_team_campaign WHERE id=?",
                (cur.lastrowid,),
            ).fetchone()
        return self._to_active_campaign(row)

    def find_active_campaign_by_message(
        self, *, channel_id: int, message_id: int
    ) -> ActiveCampaign | None:
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT {_CAMPAIGN_COLUMNS} FROM ctf_team_campaign "
                "WHERE channel_id=? AND message_id=? AND status='active'",
                (channel_id, message_id),
            ).fetchone()
        return self._to_active_campaign(row) if row else None

    def find_active_campaign_by_name(
        self,
        *,
        ctf_name: str,
    ) -> ActiveCampaign | None:
        row = self._find_campaign_by_name_row(
            ctf_name=ctf_name,
            status=CampaignStatus.ACTIVE,
        )
        return self._to_active_campaign(row) if row else None

    def find_closed_campaign_by_name(
        self,
        *,
        ctf_name: str,
        archived: bool | None = None,
    ) -> ClosedCampaign | None:
        row = self._find_campaign_by_name_row(
            ctf_name=ctf_name,
            status=CampaignStatus.CLOSED,
            archived=archived,
        )
        return self._to_closed_campaign(row) if row else None

    def _find_campaign_by_name_row(
        self,
        *,
        ctf_name: str,
        status: CampaignStatus,
        archived: bool | None = None,
    ) -> _CampaignRow | None:
        sql = (
            f"SELECT {_CAMPAIGN_COLUMNS} FROM ctf_team_campaign "
            "WHERE ctf_name=? AND status=?"
        )
        params: list[object] = [ctf_name, status.value]
        if archived is True:
            sql += " AND archived_at_unix IS NOT NULL"
        elif archived is False:
            sql += " AND archived_at_unix IS NULL"
        sql += " ORDER BY created_at_unix DESC LIMIT 1"
        with self._connection() as conn:
            return conn.execute(sql, params).fetchone()

    def list_due_campaigns(
        self, now_unix: int, limit: int = 20
    ) -> list[ActiveCampaign]:
        return self._list_active(
            "WHERE status='active' AND end_at_unix IS NOT NULL AND end_at_unix <= ? "
            "ORDER BY end_at_unix ASC LIMIT ?",
            (now_unix, limit),
        )

    def list_due_starts(self, now_unix: int, limit: int = 20) -> list[ActiveCampaign]:
        return self._list_active(
            "WHERE status='active' AND start_notified_at_unix IS NULL "
            "AND start_at_unix <= ? ORDER BY start_at_unix ASC LIMIT ?",
            (now_unix, limit),
        )

    def mark_started(self, campaign_id: int, started_at_unix: int) -> bool:
        return self._update(
            "UPDATE ctf_team_campaign SET start_notified_at_unix=? "
            "WHERE id=? AND start_notified_at_unix IS NULL AND status='active'",
            (started_at_unix, campaign_id),
        )

    def close_campaign(
        self, campaign_id: int, closed_at_unix: int, archive_at_unix: int
    ) -> bool:
        return self._update(
            "UPDATE ctf_team_campaign SET status='closed', closed_at_unix=?, "
            "archive_at_unix=? WHERE id=? AND status='active'",
            (closed_at_unix, archive_at_unix, campaign_id),
        )

    def list_due_archives(self, now_unix: int, limit: int = 20) -> list[ClosedCampaign]:
        return self._list_closed(
            "WHERE status='closed' AND archive_at_unix IS NOT NULL "
            "AND archive_at_unix <= ? AND archived_at_unix IS NULL "
            "ORDER BY archive_at_unix ASC LIMIT ?",
            (now_unix, limit),
        )

    def mark_archived(self, campaign_id: int, archived_at_unix: int) -> bool:
        return self._update(
            "UPDATE ctf_team_campaign SET archived_at_unix=? "
            "WHERE id=? AND archived_at_unix IS NULL",
            (archived_at_unix, campaign_id),
        )

    def list_campaigns(
        self, status: CampaignStatus | None, limit: int = 20
    ) -> list[Campaign]:
        if status is None:
            return self._list(
                "ORDER BY created_at_unix DESC LIMIT ?",
                (limit,),
            )
        return self._list(
            "WHERE status=? ORDER BY created_at_unix DESC LIMIT ?",
            (status.value, limit),
        )

    def _list(self, suffix: str, params: tuple[object, ...]) -> list[Campaign]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT {_CAMPAIGN_COLUMNS} FROM ctf_team_campaign {suffix}", params
            ).fetchall()
        return [self._to_campaign(row) for row in rows]

    def _list_active(
        self, suffix: str, params: tuple[object, ...]
    ) -> list[ActiveCampaign]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT {_CAMPAIGN_COLUMNS} FROM ctf_team_campaign {suffix}", params
            ).fetchall()
        return [self._to_active_campaign(row) for row in rows]

    def _list_closed(
        self, suffix: str, params: tuple[object, ...]
    ) -> list[ClosedCampaign]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT {_CAMPAIGN_COLUMNS} FROM ctf_team_campaign {suffix}", params
            ).fetchall()
        return [self._to_closed_campaign(row) for row in rows]

    def _update(self, sql: str, params: tuple[object, ...]) -> bool:
        with self._connection() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.rowcount > 0
