# ユーティリティ (utility)

## 概要

汎用コマンドを提供する。DB やランタイムへの依存なし。

## コマンド

### `/help`

`bot.tree.get_commands()` で全コマンド取得。Group コマンドは展開して `/group subcommand — description` 形式で列挙。ソートして ephemeral で応答。

### `/perms [channel]`

bot が持つ権限を ✅ / ❌ で表示する。`channel` 省略時は実行チャンネルを対象とする。

チェックする権限:

| スコープ | 権限 |
|---|---|
| Guild | `manage_roles` |
| Channel | `view_channel`, `send_messages`, `send_messages_in_threads`, `read_message_history`, `add_reactions`, `manage_channels` |
