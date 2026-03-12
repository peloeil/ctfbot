from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.db.migrations import (  # noqa: E402
    CURRENT_SCHEMA_SQL,
    CURRENT_SCHEMA_VERSION,
    EXPECTED_TABLE_COLUMNS,
)

LEGACY_TABLE_NAME = "ctf_role_campaign"
CURRENT_TABLE_NAME = "ctf_team_campaign"
LEGACY_INDEX_NAMES = (
    "idx_ctf_role_campaign_message",
    "idx_ctf_role_campaign_status_end",
    "idx_ctf_role_campaign_guild_status_created",
)
LEGACY_ADDED_COLUMNS = (
    ("discussion_channel_id", "INTEGER"),
    ("archive_at_unix", "INTEGER"),
    ("archived_at_unix", "INTEGER"),
    ("start_notified_at_unix", "INTEGER"),
    ("voice_channel_id", "INTEGER"),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a legacy ctf_role_campaign database to the current schema "
            "and optionally rename the SQLite database file."
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


def _read_table_columns(conn: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return tuple(str(row[1]) for row in rows)


def _ensure_legacy_added_columns(conn: sqlite3.Connection) -> None:
    actual_columns = set(_read_table_columns(conn, CURRENT_TABLE_NAME))
    for column_name, column_type in LEGACY_ADDED_COLUMNS:
        if column_name in actual_columns:
            continue
        conn.execute(
            f"ALTER TABLE {CURRENT_TABLE_NAME} ADD COLUMN {column_name} {column_type}"
        )
        actual_columns.add(column_name)


def _validate_current_schema(conn: sqlite3.Connection) -> None:
    for table_name, expected_columns in EXPECTED_TABLE_COLUMNS.items():
        actual_columns = _read_table_columns(conn, table_name)
        if actual_columns == expected_columns:
            continue
        raise RuntimeError(
            f"{table_name} does not match the current schema. "
            f"Expected columns: {expected_columns}. Found: {actual_columns}."
        )


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

        _ensure_legacy_added_columns(conn)
        for index_name in LEGACY_INDEX_NAMES:
            conn.execute(f"DROP INDEX IF EXISTS {index_name}")
        conn.executescript(CURRENT_SCHEMA_SQL)
        _validate_current_schema(conn)

        conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
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
