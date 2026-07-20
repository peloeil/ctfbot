# Discord 監査ログ保存 (audit_log)

## 概要

Discord サーバーの監査ログエントリを `on_audit_log_entry_create` イベントで受信し、SQLite に保存する。さらに、エントリの実行者が管理者ロール（`ADMIN_ROLE_ID`）を保持している場合は `BOT_CHANNEL_ID` のチャンネルへ通知を送る。コマンドは持たない。保存・通知とも best-effort（bot 稼働中に配信されたイベントのみ・失敗時のリトライなし・バックフィルなし）。コマンド実行記録の log_audit（`docs/core.md`）とは別機能。

## 前提

- Gateway intent: `moderation`（`Intents.default()` に含まれるため設定変更不要）
- Guild 権限: bot のロールに `View Audit Log` が必要（`/perms` のチェック項目（`docs/features/utility.md`）に含まれる）。権限がない場合、Discord はイベントを配信しないため何も保存されない（エラーにもならない）

## コマンド

なし（イベント駆動のみ）。

## イベント処理

### `on_audit_log_entry_create(entry: discord.AuditLogEntry)`

全 `AuditLogAction` を対象とし、フィルタしない。

処理:
1. `entry` から下記フィールドを抽出する
2. `changes` は `{"before": dict(entry.changes.before), "after": dict(entry.changes.after)}` を `json.dumps(..., default=str, ensure_ascii=False)` で JSON 文字列化する（Discord オブジェクト等の非 JSON 値は `str()` に落ちる）
3. `extra` は `entry.extra` が None でなければ `str(entry.extra)` を保存する
4. DB 挿入は `asyncio.to_thread` 経由で行う
5. DB 挿入が新規（`insert_audit_log_entry` が `True`）の場合のみ、「管理者操作の通知」の判定・送信を行う
6. 変換（`json.dumps`・`str()`）・挿入・通知を含む処理全体の例外を `logger.error` で記録し、raise しない（イベントを 1 件失うだけに留める）

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

再接続時の重複配信に備え、`entry_id` 重複を無視する冪等な挿入にする（挿入契約の正本は `docs/data-contracts.md`「audit_log_entry」）。

## 管理者操作の通知

エントリの実行者が管理者ロール保持者の場合、`BOT_CHANNEL_ID` のチャンネルへ通知を送る（public。ephemeral の概念はない）。

以下を**すべて**満たす場合のみ通知する。1 つでも満たさなければ何もしない（エラーにしない）:

1. DB 挿入が新規である（`insert_audit_log_entry` が `True`。再接続時の重複配信で通知が重複しないための冪等性境界。DB 保存に失敗した場合も通知しない）
2. `settings.admin_role_id` が設定されている（`None` なら通知機能は無効）
3. `entry.user_id` が `None` でない（system 実行のエントリは対象外）
4. `fetch_member(entry.guild, entry.user_id)`（`docs/core.md`）でメンバーを解決できる（脱退済み・解決失敗はスキップ）
5. 解決したメンバーが `admin_role_id` のロールを保持している

判定順は上記の通り（設定・`user_id` の安価なチェックを先に行い、API 呼び出しを伴うメンバー解決とロール判定を後段に置く）。ロール判定はイベント処理時点のロール状態で行う。操作時点との乖離（例: 操作直後に `/unsudo` した場合は通知されない）は best-effort として許容する。

送信は `send_audit_message(bot, lines)`（`docs/core.md`「チャンネルへの通知」）経由。`BOT_CHANNEL_ID` 未設定・チャンネル解決失敗時は送信しない。

## DB スキーマ

テーブル `audit_log_entry` の DDL と `Database.insert_audit_log_entry` の契約は `docs/data-contracts.md` を正本とする。

## Embed / メッセージ形式

管理者操作の通知（プレーンテキスト。embed は使わない）:

```
🛡️ <@{user_id}> が管理者操作 `{action}` を実行しました。
- 対象: {対象表記}
- メッセージ: {メッセージリンク}
- 理由: {reason}
```

- 1 行目の `{action}` は `entry.action.name`（例: `member_ban_add`。ライブラリ由来の enum 名のため sanitize 不要）
- `対象` 行は `target_id`（`getattr(entry.target, "id", None)`）が `None` の場合は行ごと省略する。`{対象表記}` は `entry.action.target_type` で決める（他の記録メッセージと同様、メンション表記は Discord 上で表示名に解決される）:

| `target_type` | 表記 |
|---|---|
| `user`・`message` | `<@{target_id}>`（`message` の `entry.target` は対象メッセージの作者） |
| `channel`・`thread` | `<#{target_id}>` |
| `role` | `<@&{target_id}>` |
| `emoji` | `:{name}:`（名前は下記の解決規則。解決できない場合は `- 対象 ID: {target_id}`） |
| それ以外（`sticker`・`webhook` 等） | 名前を解決できれば `{name}`、できなければ行を `- 対象 ID: {target_id}` とする |

- 名前の解決規則: `entry.target.name` → `entry.changes.after.name` → `entry.changes.before.name` の順で最初に得られた値に `sanitize_audit_text` を適用する（対象が削除済みでも `changes` に名前が残っていれば表示できる）
- `メッセージ` 行は `entry.extra` が `message_id` と `channel` を持つ場合（`message_pin`・`message_unpin`）のみ、`https://discord.com/channels/{guild_id}/{channel_id}/{message_id}` を表示する。それ以外の場合は行ごと省略する（`message_delete` はメッセージが消滅済みでリンク不可）
- `理由` 行は `reason` が `None` の場合は行ごと省略する。値は `sanitize_audit_text`（`docs/core.md`「コマンド実行ログ」の sanitize 規則）を適用する
- `changes` の内容は通知に含めない（DB 参照で足りる。通知はノイズを抑える）
- メンション抑止（`AllowedMentions.none()`）と 1900 文字切り詰めは `send_audit_message` の契約に従う

## 関連設定

専用の環境変数はない。管理者操作の通知は `ADMIN_ROLE_ID`（管理者ロール判定）と `BOT_CHANNEL_ID`（通知先）を参照する（定義は `docs/data-contracts.md`）。いずれかが未設定の場合、保存のみ行い通知はスキップする。

## 対象外

- 保存済みログの参照・検索コマンド
- bot 起動前に発生したエントリのバックフィル（`guild.audit_logs()` での遡及取得）
- 保持期間・自動削除（保存量は単調増加する。肥大化した場合は `(guild_id, created_at_unix)` index を使い期間指定で手動削除する）
- burst 時の流量制御（イベントごとに `asyncio.to_thread` へ委譲するのみで、キュー上限・backpressure は設けない）
- 通知失敗時のリトライ（`send_safely` の best-effort に従う）
- アクション種別による通知のフィルタ・購読設定（全アクションを対象とする）
- 操作時点のロール保持判定（判定はイベント処理時点のみ）
