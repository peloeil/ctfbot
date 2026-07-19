# bot 共通挙動

## 概要

全 feature が共有する応答・通知の挙動を定義する。この文書が正本である。

## 実行コンテキスト

**全コマンドは guild 限定とする。** スラッシュコマンドは `GUILD_ID` の guild にのみ登録するため（`docs/design.md`「前提: 単一 guild 運用」）、DM にコマンドは露出しない。`require_guild` は通常到達しない防御的境界として維持し、guild 外での実行には「サーバー内で実行してください。」を ephemeral で応答する（`ServiceError`）。DM でのコマンド対応は非目標。

この宣言により、`log_audit` の書式（`#{実行チャンネル名}` を含む）は guild コンテキストを前提としてよい。

## コマンド応答

- `send_interaction(interaction, content, ephemeral=True) -> None`: コマンド応答の共通経路（bot 内部依存を持たない `utility.py` のみ例外で、直接 `interaction.response` を使い同じ応答契約を満たす）。デフォルト ephemeral（public にする場合のみ呼び出し側が明示）。初回応答済み（defer 含む）なら followup へ自動で切り替える。メンションは常に `AllowedMentions.none()`。送信失敗（`InteractionResponded`・`NotFound`・`HTTPException`）は例外ログのみで raise しない
- `require_guild(interaction) -> Guild`: guild 外での実行に `ServiceError("サーバー内で実行してください。")` を raise する

## チャンネルへの通知

- `resolve_messageable(bot, channel_id) -> Messageable | None`: 設定されたチャンネル ID を cache → fetch の順で解決する。ID が未設定（None）・解決失敗（`NotFound`・`Forbidden`・`HTTPException`）・送信可能でない場合は None を返し、呼び出し側は通知をスキップする。解決失敗（未設定を除く）は warning ログを 1 行残す（設定不良の検知手段）
- `send_safely(channel, content=None, embed=None, allowed_mentions=None) -> Message | None`: チャンネルへ送信し、失敗（`HTTPException`）時は例外ログを残して None を返す（raise しない）。通知の失敗で主処理を壊さないための境界。`allowed_mentions` は呼び出し側が明示する（省略時はライブラリ既定）

メンション方針: 実際に ping してよいのはメンバーメンションのみ。ユーザー入力（CTF 名等）を含む文面は `AllowedMentions.none()` で、メンバー列挙チャンク（開始通知・スナップショット・参加通知）は users のみ許可（everyone・roles 拒否）で送る。

## 共通エラーハンドラ

cog が処理しなかったコマンドの例外は `app.py` の `bot.tree.error` ハンドラに届く。応答はいずれも ephemeral:

| 例外 | 応答 |
|---|---|
| `CommandOnCooldown` | `コマンドはクールダウン中です。` |
| `MissingPermissions` | `このコマンドを実行する権限がありません。` |
| その他 | error ログ + `コマンド実行中にエラーが発生しました。` |

## コマンド実行ログ (log_audit)

コマンド実行の記録を `BOT_CHANNEL_ID` のチャンネルへ送信する（未設定・チャンネル解決失敗時は何もしない）。Discord AuditLog を DB へ保存する「Discord 監査ログ保存」（`docs/features/audit-log.md`）とは別機能。

```
📝 <@{user_id}> が <#{channel_id}> で `/{command_name}` を実行しました。
- {details の各行}
```

- `AllowedMentions.none()` 付きで送信する（実行者・チャンネルのメンションは表示のみで通知は飛ばない）
- command_name・details を sanitize する: 空白を 1 つに正規化し、`<@` にゼロ幅スペースを挿入（ユーザー入力による ping を無効化）
- 1900 文字（`MAX_AUDIT_CONTENT_LENGTH`。2000 文字制限へのマージン）を超える場合は 1897 文字に切り詰めて `...` を付ける（`...` 込みで 1900 文字以内）
- `channel_id` を持たないコンテキストでは `unknown` と表示する（全コマンド guild 限定のため通常は発生しない）

## 表示テキストの escape 方針

- ping 抑止はメンション制御（`AllowedMentions`）と log_audit の sanitize で行う（上記）
- log_audit 以外では Markdown escape を行わない。平文・Embed 本文に含まれる外部由来文字列（CTF 名・challenge 名等）による表示崩れは許容する
- 例外: Embed 内のリンク `[名前](URL)` に埋め込む外部由来の値がリンク構文を壊す文字（`]`・`(`・`)`）を含む場合は、リンク化せず名前のみを表示する（URL 側が壊れている場合はリンク行自体を省略する）

## 接続状態通知

`BOT_STATUS_CHANNEL_ID` のチャンネルへ送信する（未設定なら何もしない）:

- 初回の ready 時のみ: `🟢 ctfbot が接続しました ({YYYY-MM-DD HH:MM:SS TZ})`（再接続では送らない）
- SIGINT による終了時のみ: `🔴 ctfbot が停止します ({同書式})`
- SIGTERM 等それ以外の終了経路では切断通知を送らない（非目標）

## 関連設定

環境変数の定義は `docs/data-contracts.md`「設定契約」を正本とする。
