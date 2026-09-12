# ユーティリティ (utility)

汎用コマンドを提供する。DB やランタイムへの依存なし。`/roll` 以外の応答は
ephemeral。

実装: [utility.py](../../src/ctfbot/features/utility.py)。検証: [test_utility.py](../../tests/test_utility.py)。

## コマンド

### `/roll <notation>`

`notation` を `NdM` 形式（例: `3d6`）で受け取り、各ダイスの出目と合計を
チャンネルに公開する。ダイスの個数・面数はいずれも 1〜100 とする。

形式または範囲が不正な場合は、理由を ephemeral で応答する。

### `/help`

`bot.tree.get_commands(guild=interaction.guild)` で guild 登録の全コマンドを取得する（起動時に `copy_global_to` で guild へコピーしたものが Discord に登録されるため、guild を指定して取得する）。Group コマンドは 1 段だけ展開して `/group subcommand — description` 形式で（ネストした subgroup の子は列挙しない）、単発コマンドは `/command — description` 形式で列挙し、行の文字列を辞書順にソートして応答。description は各コマンド定義の値をそのまま表示する。

応答の分割・切り詰めは非目標とする。

### `/perms [channel] [role]`

Discord が扱う全権限について、Guild での実効権限を `Guild ✅ name、...` / `Guild ❌ name、...` 形式で表示する。Channel は Guild での実効権限と比較し、異なる権限だけを `Channel 追加 ✅ name、...` / `Channel 削除 ❌ name、...` 形式で表示する。差分がなければ `Channel 差分なし` と表示する。対象とチャンネルの mention・IDも表示し、ロール指定時はロール順位も表示する。

`channel`（`discord.TextChannel` のみ指定可）省略時は実行チャンネルを対象とする。`role`（`discord.Role` のみ指定可）省略時は bot 自身を対象とし、指定時は `@everyone` の権限も合成したそのロールの権限を対象とする。Channel 権限には `@everyone` と指定ロールの channel overwrite も反映する。応答が Discord の文字数上限を超える場合は Guild と Channel に分割する。

エラーケース:

- guild 外で実行 → 「サーバー内で実行してください。」
- 対象が GuildChannel でない → 「チャンネル権限を確認できません。」

## 必要な Bot 権限

| スコープ | 権限 |
|---|---|
| Guild | `view_audit_log`, `manage_roles` |
| Channel | `view_channel`, `send_messages`, `send_messages_in_threads`, `read_message_history`, `add_reactions`, `manage_channels`, `embed_links` |
