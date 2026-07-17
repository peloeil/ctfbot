# bot 共通挙動

## 概要

全 feature が共有する応答・通知の挙動を定義する。実装は `helpers.py`・`app.py` を正とする。

## コマンド応答

- `send_interaction`: コマンド応答の共通経路。デフォルト ephemeral（public にする場合のみ呼び出し側が明示）。初回応答済み（defer 含む）なら followup へ自動で切り替える。メンションは常に `AllowedMentions.none()`。送信失敗は例外ログのみで raise しない
- `require_guild`: guild 外での実行に `ServiceError("サーバー内で実行してください。")` を raise する

## チャンネルへの通知

- `resolve_messageable`: 設定されたチャンネル ID を cache → fetch の順で解決する。ID が未設定（None）・解決失敗・送信可能でない場合は None を返し、通知は黙ってスキップされる
- `send_safely`: チャンネルへ送信し、失敗時は例外ログを残して None を返す（raise しない）。通知の失敗で主処理を壊さないための境界

## 共通エラーハンドラ

cog が処理しなかったコマンドの例外は `app.py` の `bot.tree.error` ハンドラに届く。応答はいずれも ephemeral:

| 例外 | 応答 |
|---|---|
| `CommandOnCooldown` | `コマンドはクールダウン中です。` |
| `MissingPermissions` | `このコマンドを実行する権限がありません。` |
| その他 | error ログ + `コマンド実行中にエラーが発生しました。` |

## 監査ログ (log_audit)

コマンド実行の記録を `BOT_CHANNEL_ID` のチャンネルへ送信する（未設定なら何もしない）。

```
📝 `{実行者 display_name}` (id={user_id}) が #{実行チャンネル名} で `/{command_name}` を実行しました。
- {details の各行}
```

- 全フィールドを sanitize する: 空白を 1 つに正規化し、`<@` にゼロ幅スペースを挿入（ユーザー入力による ping を無効化）
- `AllowedMentions.none()` 付きで送信
- 1900 文字（`MAX_AUDIT_CONTENT_LENGTH`。2000 文字制限へのマージン）を超えたら末尾を `...` に切り詰め

## 接続状態通知

`BOT_STATUS_CHANNEL_ID` のチャンネルへ送信する（未設定なら何もしない）:

- 初回の ready 時のみ: `🟢 ctfbot connected at {YYYY-MM-DD HH:MM:SS TZ}`（再接続では送らない）
- SIGINT による終了時のみ: `🔴 ctfbot disconnecting at {同書式}`

## 関連設定

| 環境変数 | デフォルト | 説明 |
|---|---|---|
| `BOT_CHANNEL_ID` | 0 | 監査ログの送信先（0 で無効） |
| `BOT_STATUS_CHANNEL_ID` | 0 | 接続状態通知の送信先（0 で無効） |
