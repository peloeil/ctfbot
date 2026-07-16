# 監査ログ保存 (audit_log)

## 概要

Discord サーバーの監査ログエントリを `on_audit_log_entry_create` イベントで受信し、SQLite に保存する。保存専用でコマンドは持たない。

## 前提

- Gateway intent: `moderation`（`Intents.default()` に含まれるため設定変更不要）
- Guild 権限: bot のロールに `View Audit Log` が必要（README「Bot に必要な権限」・`/perms` のチェック項目に含まれる）。権限がない場合、Discord はイベントを配信しないため何も保存されない（エラーにもならない）

## コマンド

なし（保存専用）。

## イベント処理

### `on_audit_log_entry_create(entry: discord.AuditLogEntry)`

全 `AuditLogAction` を対象とし、フィルタしない。

処理:
1. `entry` から下記フィールドを抽出する
2. `changes` は `{"before": dict(entry.changes.before), "after": dict(entry.changes.after)}` を `json.dumps(..., default=str, ensure_ascii=False)` で JSON 文字列化する（Discord オブジェクト等の非 JSON 値は `str()` に落ちる）
3. `extra` は `entry.extra` が None でなければ `str(entry.extra)` を保存する
4. DB 挿入は `asyncio.to_thread` 経由で行う
5. `RepositoryError` は `logger.error` で記録し、raise しない（イベントループを止めない）

| カラム | 取得元 |
|---|---|
| `entry_id` | `entry.id` |
| `guild_id` | `entry.guild.id` |
| `action` | `entry.action.name`（例: `channel_create`, `member_ban_add`） |
| `user_id` | `entry.user_id`（実行者。system の場合 None） |
| `target_id` | `getattr(entry.target, "id", None)` |
| `reason` | `entry.reason` |
| `changes_json` | 上記 2 の JSON 文字列 |
| `extra_text` | 上記 3 の文字列 |
| `created_at_unix` | `int(entry.created_at.timestamp())` |

再接続時の重複配信に備え、`INSERT OR IGNORE` + `entry_id` の UNIQUE 制約で冪等にする。

## データモデル

dataclass は定義しない。保存専用で読み取りパスがないため、`Database` メソッドはキーワード引数を直接受け取る。

```python
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
) -> bool:  # True: 挿入した / False: 重複でスキップ
```

## DB スキーマ

`_SCHEMA_DDL` に定義され、`_MIGRATIONS[1]`（version 1 → 2 の移行）にも同じ DDL（`IF NOT EXISTS` 付き）が登録されている。

```sql
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
```

## Embed / メッセージ形式

なし（Discord への送信は行わない）。

## 関連設定

新規環境変数なし。

## 対象外

- 保存済みログの参照・検索コマンド
- bot 起動前に発生したエントリのバックフィル（`guild.audit_logs()` での遡及取得）
- 保持期間・自動削除
