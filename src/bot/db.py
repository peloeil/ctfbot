import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from bot.errors import ConflictError, RepositoryError
from bot.features.ctf_team.models import Campaign, CampaignStatus

CURRENT_SCHEMA_VERSION = 1
_MIGRATIONS: dict[int, str] = {}

_SCHEMA_DDL = """\
CREATE TABLE IF NOT EXISTS alpacahack_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS ctf_team_campaign (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
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
    UNIQUE (guild_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_campaign_guild_message
    ON ctf_team_campaign (guild_id, channel_id, message_id, status);
CREATE INDEX IF NOT EXISTS idx_campaign_status_end
    ON ctf_team_campaign (status, end_at_unix);
CREATE INDEX IF NOT EXISTS idx_campaign_guild_status
    ON ctf_team_campaign (guild_id, status, created_at_unix);
CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_active_name_unique
    ON ctf_team_campaign (guild_id, ctf_name)
    WHERE status = 'active';
"""

_CAMPAIGN_COLUMNS = (
    "id, guild_id, channel_id, message_id, role_id, ctf_name, "
    "start_at_unix, end_at_unix, status, created_by, created_at_unix, "
    "start_notified_at_unix, closed_at_unix, archive_at_unix, archived_at_unix, "
    "discussion_channel_id, voice_channel_id"
)


class Database:
    def __init__(self, path: str) -> None:
        self._path = str(Path(path).expanduser().resolve())
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=10.0)
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
    def _to_campaign(row: tuple) -> Campaign:
        return Campaign(
            id=row[0],
            guild_id=row[1],
            channel_id=row[2],
            message_id=row[3],
            role_id=row[4],
            ctf_name=row[5],
            start_at_unix=row[6],
            end_at_unix=row[7],
            status=CampaignStatus(row[8]),
            created_by=row[9],
            created_at_unix=row[10],
            start_notified_at_unix=row[11],
            closed_at_unix=row[12],
            archive_at_unix=row[13],
            archived_at_unix=row[14],
            discussion_channel_id=row[15],
            voice_channel_id=row[16],
        )

    def add_alpacahack_user(self, name: str) -> bool:
        clean = name.strip()
        if not clean:
            raise RepositoryError("AlpacaHack username must not be empty.")
        with self._connection() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO alpacahack_user (name) VALUES (?)", (clean,)
            )
            conn.commit()
            return cur.rowcount > 0

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

    def count_active_campaigns_by_creator(self, guild_id: int, created_by: int) -> int:
        with self._connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM ctf_team_campaign "
                "WHERE guild_id=? AND created_by=? AND status='active'",
                (guild_id, created_by),
            ).fetchone()[0]

    def has_active_campaign_with_name(self, guild_id: int, ctf_name: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM ctf_team_campaign "
                "WHERE guild_id=? AND ctf_name=? AND status='active' LIMIT 1",
                (guild_id, ctf_name),
            ).fetchone()
        return row is not None

    def create_campaign(
        self,
        *,
        guild_id: int,
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
    ) -> Campaign:
        if self.has_active_campaign_with_name(guild_id, ctf_name):
            raise ConflictError("Active campaign already exists.")
        with self._connection() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO ctf_team_campaign ("
                    "guild_id, channel_id, message_id, role_id, "
                    "discussion_channel_id, voice_channel_id, ctf_name, "
                    "start_at_unix, end_at_unix, status, created_by, created_at_unix"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                    (
                        guild_id,
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
                raise ConflictError("Active campaign already exists.") from exc
            conn.commit()
            row = conn.execute(
                f"SELECT {_CAMPAIGN_COLUMNS} FROM ctf_team_campaign WHERE id=?",
                (cur.lastrowid,),
            ).fetchone()
        return self._to_campaign(row)

    def find_active_campaign_by_message(
        self, *, guild_id: int, channel_id: int, message_id: int
    ) -> Campaign | None:
        with self._connection() as conn:
            row = conn.execute(
                f"SELECT {_CAMPAIGN_COLUMNS} FROM ctf_team_campaign "
                "WHERE guild_id=? AND channel_id=? "
                "AND message_id=? AND status='active'",
                (guild_id, channel_id, message_id),
            ).fetchone()
        return self._to_campaign(row) if row else None

    def find_campaign_by_name(
        self,
        *,
        guild_id: int,
        ctf_name: str,
        status: CampaignStatus,
        archived: bool | None = None,
    ) -> Campaign | None:
        sql = (
            f"SELECT {_CAMPAIGN_COLUMNS} FROM ctf_team_campaign "
            "WHERE guild_id=? AND ctf_name=? AND status=?"
        )
        params: list[object] = [guild_id, ctf_name, status.value]
        if archived is True:
            sql += " AND archived_at_unix IS NOT NULL"
        elif archived is False:
            sql += " AND archived_at_unix IS NULL"
        sql += " ORDER BY created_at_unix DESC LIMIT 1"
        with self._connection() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._to_campaign(row) if row else None

    def list_due_campaigns(self, now_unix: int, limit: int = 20) -> list[Campaign]:
        return self._list(
            "WHERE status='active' AND end_at_unix IS NOT NULL AND end_at_unix <= ? "
            "ORDER BY end_at_unix ASC LIMIT ?",
            (now_unix, limit),
        )

    def list_due_starts(self, now_unix: int, limit: int = 20) -> list[Campaign]:
        return self._list(
            "WHERE status='active' AND start_notified_at_unix IS NULL "
            "AND start_at_unix <= ? ORDER BY start_at_unix ASC LIMIT ?",
            (now_unix, limit),
        )

    def mark_started(self, campaign_id: int, started_at_unix: int) -> bool:
        return self._update(
            "UPDATE ctf_team_campaign SET start_notified_at_unix=? "
            "WHERE id=? AND start_notified_at_unix IS NULL",
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

    def list_due_archives(self, now_unix: int, limit: int = 20) -> list[Campaign]:
        return self._list(
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
        self, guild_id: int, status: CampaignStatus | None, limit: int = 20
    ) -> list[Campaign]:
        if status is None:
            return self._list(
                "WHERE guild_id=? ORDER BY created_at_unix DESC LIMIT ?",
                (guild_id, limit),
            )
        return self._list(
            "WHERE guild_id=? AND status=? ORDER BY created_at_unix DESC LIMIT ?",
            (guild_id, status.value, limit),
        )

    def _list(self, suffix: str, params: tuple[object, ...]) -> list[Campaign]:
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT {_CAMPAIGN_COLUMNS} FROM ctf_team_campaign {suffix}", params
            ).fetchall()
        return [self._to_campaign(row) for row in rows]

    def _update(self, sql: str, params: tuple[object, ...]) -> bool:
        with self._connection() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.rowcount > 0
