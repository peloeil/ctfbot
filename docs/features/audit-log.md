# Discord 監査ログ保存 (audit_log)

## 概要

Discord サーバーの監査ログエントリを `on_audit_log_entry_create` イベントで受信し、SQLite に保存する。保存専用でコマンドは持たない。保存は best-effort（bot 稼働中に配信されたイベントのみ・失敗時のリトライなし・バックフィルなし）。コマンド実行記録の log_audit（`docs/core.md`）とは別機能。

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
5. 変換（`json.dumps`・`str()`）と挿入を含む処理全体の例外を `logger.error` で記録し、raise しない（イベントを 1 件失うだけに留める）

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

再接続時の重複配信に備え、`INSERT ... ON CONFLICT(entry_id) DO NOTHING` で冪等にする（`entry_id` 重複のみを無視し、他の制約違反はエラーとして観測する。契約は `docs/data-contracts.md`）。

## データモデル

dataclass は定義しない。保存専用で読み取りパスがないため、`Database.insert_audit_log_entry`（契約は `docs/data-contracts.md` を正本とする）はカラム値をキーワード引数で直接受け取り、挿入したら `True`、`entry_id` 重複でスキップしたら `False` を返す。

## DB スキーマ

テーブル `audit_log_entry` の DDL は `docs/data-contracts.md` を正本とする（version 1 → 2 の移行にも同じ DDL が `IF NOT EXISTS` 付きで登録されている）。設計上のポイント:

- `entry_id` に UNIQUE 制約（上記の冪等 insert の前提）
- `(guild_id, created_at_unix)` に index（期間指定の手動削除・将来の参照用）

## Embed / メッセージ形式

なし（Discord への送信は行わない）。

## 関連設定

新規環境変数なし。

## 対象外

- 保存済みログの参照・検索コマンド
- bot 起動前に発生したエントリのバックフィル（`guild.audit_logs()` での遡及取得）
- 保持期間・自動削除（保存量は単調増加する。肥大化した場合は `(guild_id, created_at_unix)` index を使い期間指定で手動削除する）
