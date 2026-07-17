# ユーティリティ (utility)

## 概要

汎用コマンドを提供する。DB やランタイムへの依存なし。応答はすべて ephemeral。

## コマンド

### `/help`

`bot.tree.get_commands()` で全コマンド取得。Group コマンドは展開して `/group subcommand — description` 形式で、単発コマンドは `/command — description` 形式で列挙し、行の文字列を辞書順にソートして応答。

既知の制限: 応答の分割・切り詰めは行わないため、コマンド数の増加で Discord の 2000 文字上限に達すると送信に失敗する。

### `/perms [channel]`

bot が持つ権限を `{✅|❌} {スコープ} {権限名}` の行区切りで表示する（例: `✅ Guild manage_roles`）。`channel`（`discord.TextChannel` のみ指定可）省略時は実行チャンネルを対象とする。

エラーケース:
- guild 外で実行 → 「サーバー内で実行してください。」
- 対象が GuildChannel でない → 「チャンネル権限を確認できません。」

チェックする権限（表示順）:

| スコープ | 権限 |
|---|---|
| Guild | `view_audit_log`, `manage_roles` |
| Channel | `view_channel`, `send_messages`, `send_messages_in_threads`, `read_message_history`, `add_reactions`, `manage_channels` |
