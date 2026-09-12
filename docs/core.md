# bot 共通挙動

コマンド応答、通知、メンション制御を変更するときに参照する。実装は [helpers.py](../src/ctfbot/helpers.py)・[app.py](../src/ctfbot/app.py)、検証は [test_helpers.py](../tests/test_helpers.py)・[test_app.py](../tests/test_app.py)。機能固有の応答は [各機能仕様](../README.md#機能) を参照する。

## コマンド応答

全コマンドは guild 限定。`require_guild` は guild 外で `ServiceError` とし、「サーバー内で実行してください。」を ephemeral で返す。

`send_interaction` はデフォルト ephemeral。public 応答は呼び出し側で指定する。初回応答済み（defer 含む）なら followup を使い、メンションを抑止する。`InteractionResponded`・`NotFound`・`HTTPException` はログに残して送出しない。

cog が処理しなかった例外は `bot.tree.error` に届く。応答はすべて ephemeral。

| 例外 | 応答 |
|---|---|
| `CommandOnCooldown` | コマンドはクールダウン中です。 |
| `MissingPermissions` | このコマンドを実行する権限がありません。 |
| その他 | error ログ + コマンド実行中にエラーが発生しました。 |

## チャンネルへの通知

| 関数 | 保証 |
|---|---|
| `resolve_messageable` | ID を cache → fetch で解決する。未設定・解決失敗・送信不可なら `None`。未設定以外の失敗は warning ログ |
| `send_safely` | HTTP 送信失敗をログに残して `None` を返す。メンション制御は呼び出し側が指定し、省略時はライブラリ既定 |
| `fetch_member` | cache → fetch で解決する。`NotFound`・`Forbidden`・`HTTPException` は `None` |
| `send_audit_message` | `BOT_CHANNEL_ID` へ行を改行結合して送り、メンションを抑止する。未設定・解決失敗ならスキップ |

`send_audit_message` は 1900 文字超過時に 1897 文字 + `...` へ切り詰める。表示用メンションを壊さないため、sanitize は呼び出し側がユーザー入力に対して行う。

`paginate_lines` は Embed description 用に、行を改行で結合して 4096 文字以下のページへ分割する。超過する行は断片に分けて内容を残す。ページ先頭の空行は省き、ページ内の空行は保つ。空の入力・全行空文字は空リストとし、空ページを返さない。通常メッセージ用の 1900 文字制限とは用途が異なる。

## メンションと表示

ping を許可するのは、メンバーメンション、AlpacaHack Daily の `ALPACAHACK_MENTION_ID`、募集メッセージの募集ロール。ユーザー入力を含むヘッダー等は `AllowedMentions.none()`、メンバー列挙は users のみ許可する。

`sanitize_audit_text` は空白を 1 つに正規化し、`<@` にゼロ幅スペースを挿入する。コマンド実行ログの command_name・details、管理者操作通知の名前・理由に適用する。

外部由来の平文・Embed 本文は Markdown escape せず、表示崩れを許容する。ただしリンクの名前や URL に `]`・`(`・`)` が含まれる場合はリンク化せず名前のみ表示する。CTFtime のリンク行は URL が空または不正なら行ごと省略する。

## コマンド実行ログ

`log_audit` は `send_audit_message` を使い、実行者・チャンネル・コマンド名・details を記録する。メンションは表示のみで通知しない。チャンネル ID がない場合は `unknown` と表示する。

[Discord 監査ログ保存](features/audit-log.md) は Discord の操作イベントを DB に保存する機能で、このコマンド実行記録とは独立している。正確な文面は `helpers.py` を参照する。

## 接続状態通知

`BOT_CHANNEL_ID` へ接続・停止時刻を付けて通知する。

- 初回 ready 時に接続通知を送り、再接続では送らない。
- SIGINT による終了時に停止通知を送る。
- SIGTERM 等の終了経路では停止通知を送らない。
