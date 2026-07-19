# ユーティリティ (utility)

## 概要

汎用コマンドを提供する。DB やランタイムへの依存なし。応答はすべて ephemeral。

## コマンド

### `/help`

`bot.tree.get_commands(guild=interaction.guild)` で guild 登録の全コマンドを取得する（起動時に global コマンドを guild へコピーし global 登録を削除するため、guild を指定しない取得は空になる）。Group コマンドは 1 段だけ展開して `/group subcommand — description` 形式で（ネストした subgroup の子は列挙しない）、単発コマンドは `/command — description` 形式で列挙し、行の文字列を辞書順にソートして応答。description は各コマンド定義の値をそのまま表示する。

応答の分割・切り詰めは非目標とする。

### `/perms [channel]`

bot が持つ権限を `{✅|❌} {スコープ} {権限名}` の行区切りで表示する（例: `✅ Guild manage_roles`）。`channel`（`discord.TextChannel` のみ指定可）省略時は実行チャンネルを対象とする。

エラーケース:
- guild 外で実行 → 「サーバー内で実行してください。」
- 対象が GuildChannel でない → 「チャンネル権限を確認できません。」

チェックする権限（表示順）。この表が bot に必要な権限一覧の正本である:

| スコープ | 権限 |
|---|---|
| Guild | `view_audit_log`, `manage_roles` |
| Channel | `view_channel`, `send_messages`, `send_messages_in_threads`, `read_message_history`, `add_reactions`, `manage_channels`, `embed_links` |
