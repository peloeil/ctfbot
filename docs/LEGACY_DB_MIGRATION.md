# Legacy DB Migration

旧 `ctf_role_campaign` を含む SQLite DB を、current schema の `ctf_team_campaign` に手動移行するための手順です。

この bot は current-only です。旧 schema のままでは起動時に拒否されます。

## 対象

- 既存の SQLite DB に `ctf_role_campaign` テーブルがある
- その DB を current 版の bot で継続利用したい

新規セットアップでは不要です。空の DB から起動すると current schema が自動作成されます。

## 手順

1. bot を停止する
2. 対象 DB をバックアップする
3. 次のコマンドを手動実行する

```bash
uv run python scripts/migrate_ctf_team_db.py <db_path>
```

DB ファイル名もこのタイミングで変えたい場合は `--rename-to` を使います。

```bash
uv run python scripts/migrate_ctf_team_db.py <db_path> --rename-to ctfbot.db
```

成功すると、script は移行後の DB path を表示します。

## 注意

- この移行は通常フローには含まれません。必要な環境でのみ手動実行します
- `ctf_role_campaign` と `ctf_team_campaign` が同時に存在する DB など、曖昧な状態の DB は script 側で拒否されます
- 移行後は bot を再起動します
