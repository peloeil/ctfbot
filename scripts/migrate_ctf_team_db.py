from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

TARGET_USER_VERSION = 7
LEGACY_TABLE_NAME = "ctf_role_campaign"
CURRENT_TABLE_NAME = "ctf_team_campaign"
LEGACY_INDEX_NAMES = (
    "idx_ctf_role_campaign_message",
    "idx_ctf_role_campaign_status_end",
    "idx_ctf_role_campaign_guild_status_created",
)
CURRENT_INDEX_STATEMENTS = (
    """
    CREATE INDEX IF NOT EXISTS idx_ctf_team_campaign_message
        ON ctf_team_campaign (guild_id, channel_id, message_id, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ctf_team_campaign_status_end
        ON ctf_team_campaign (status, end_at_unix)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ctf_team_campaign_guild_status_created
        ON ctf_team_campaign (guild_id, status, created_at_unix)
    """,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rename the legacy ctf_role_campaign table to ctf_team_campaign and "
            "optionally rename the SQLite database file."
        )
    )
    parser.add_argument("db_path", help="Path to the SQLite database file to migrate.")
    parser.add_argument(
        "--rename-to",
        dest="rename_to",
        help=(
            "Optional destination path to rename the SQLite "
            "database file before migration."
        ),
    )
    return parser.parse_args()


def _resolve_database_path(db_path: str, rename_to: str | None) -> Path:
    source = Path(db_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Database file does not exist: {source}")

    if rename_to is None:
        return source

    destination = Path(rename_to).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Destination database already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)
    return destination


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def migrate_database(db_path: Path) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        has_legacy_table = _table_exists(conn, LEGACY_TABLE_NAME)
        has_current_table = _table_exists(conn, CURRENT_TABLE_NAME)

        if has_legacy_table and has_current_table:
            raise RuntimeError(
                "Both legacy and current campaign tables exist. Resolve manually."
            )
        if not has_legacy_table and not has_current_table:
            raise RuntimeError(
                "Neither ctf_role_campaign nor ctf_team_campaign exists."
            )

        if has_legacy_table:
            conn.execute(
                f"ALTER TABLE {LEGACY_TABLE_NAME} RENAME TO {CURRENT_TABLE_NAME}"
            )

        for index_name in LEGACY_INDEX_NAMES:
            conn.execute(f"DROP INDEX IF EXISTS {index_name}")
        for statement in CURRENT_INDEX_STATEMENTS:
            conn.execute(statement)

        conn.execute(f"PRAGMA user_version = {TARGET_USER_VERSION}")
        conn.commit()


def main() -> int:
    args = _parse_args()
    try:
        db_path = _resolve_database_path(args.db_path, args.rename_to)
        migrate_database(db_path)
    except Exception as error:
        print(error, file=sys.stderr)
        return 1

    print(f"Migrated database: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
