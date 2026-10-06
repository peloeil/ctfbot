# ユーティリティ (utility)

汎用コマンドを提供する。DB やランタイムへの依存なし。`/roll` 以外の応答は
ephemeral。

実装: [utility.py](../../src/ctfbot/features/utility.py)。検証: [test_utility.py](../../tests/test_utility.py)。

## コマンド

### `/roll <notation>`

`notation` を `NdM` 形式（例: `3d6`）で受け取り、各ダイスの出目と合計を
チャンネルに公開する。ダイスの個数・面数はいずれも 1〜100 とする。

形式または範囲が不正な場合は、理由を ephemeral で応答する。

### `/help [command]`

`command` を省略すると、guild 登録の全コマンドを一覧表示する。Group コマンドは 1 段だけ展開して `/group subcommand — description` 形式で（ネストした subgroup の子は列挙しない）、単発コマンドは `/command — description` 形式で列挙し、行の文字列を辞書順にソートする。description は各コマンド定義の値をそのまま表示する。

`command` を指定すると、そのコマンドの説明・使い方・引数の必須/任意・既定値・選択肢を表示する。例: `/help command:roll`、`/help command:ctfteam open`。先頭の `/` は任意で、前後やコマンド名の間の余分な空白は無視する。グループを指定した場合は説明と直下のサブコマンド一覧を表示し、ネストしたサブコマンドも名前を空白区切りで指定できる。

詳細文は各コマンド定義の `extras["help"]` に置き、利用条件や副作用など引数定義だけでは分からない内容を補う。使い方・引数情報は登録された定義から生成する。詳細文のない拡張コマンドも、通常の説明と引数情報を表示する。引数のないコマンドは「引数: なし」と表示する。空白だけの指定や存在しないコマンド名には、見つからない旨と `/help` の案内を返す。

一覧・詳細とも `bot.tree.get_commands(guild=interaction.guild)` を参照する（起動時に `copy_global_to` で guild へコピーしたものが Discord に登録されるため）。ヘルプ対象のコマンドは実行せず、応答はすべて ephemeral。

応答の分割・切り詰めは非目標とする。

### `/perms [channel] [role]`

Discord が扱う全権限について、Guild での実効権限を `Guild ✅ name、...` / `Guild ❌ name、...` 形式で表示する。Channel は Guild での実効権限と比較し、異なる権限だけを `Channel 追加 ✅ name、...` / `Channel 削除 ❌ name、...` 形式で表示する。差分がなければ `Channel 差分なし` と表示する。対象とチャンネルの mention・IDも表示し、ロール指定時はロール順位も表示する。

`channel`（`discord.TextChannel` のみ指定可）省略時は実行チャンネルを対象とする。`role`（`discord.Role` のみ指定可）省略時は bot 自身を対象とし、指定時は `@everyone` の権限も合成したそのロールの権限を対象とする。Channel 権限には `@everyone` と指定ロールの channel overwrite も反映する。応答が Discord の文字数上限を超える場合は Guild と Channel に分割する。

エラーケース:

- guild 外で実行 → 「サーバー内で実行してください。」
- 対象が GuildChannel でない → 「チャンネル権限を確認できません。」

## 必要な Bot 権限

全機能を使う場合、Bot に以下の実効権限が必要になる。`@everyone` から継承できる権限は重複付与する必要はない。

| Discord の英語表示名 | 権限名 | 用途 |
|---|---|---|
| View Channels | `view_channel` | 対象チャンネルの閲覧 |
| Read Message History | `read_message_history` | 募集メッセージの取得 |
| Send Messages | `send_messages` | 募集・通知・応答の送信 |
| Send Messages in Threads | `send_messages_in_threads` | スレッド内での応答と archive 時の投稿禁止設定 |
| Create Public Threads | `create_public_threads` | archive 時に公開スレッドの作成を禁止する設定 |
| Create Private Threads | `create_private_threads` | archive 時にプライベートスレッドの作成を禁止する設定 |
| Send Voice Messages | `send_voice_messages` | archive 時にボイスメッセージの送信を禁止する設定 |
| Create Polls | `send_polls` | archive 時に投票の作成を禁止する設定 |
| Embed Links | `embed_links` | CTFtime・AlpacaHack・募集一覧の Embed 送信 |
| Add Reactions | `add_reactions` | 募集メッセージへの ✅ 追加 |
| Manage Channels | `manage_channels` | チャンネルの作成・移動・削除 |
| Manage Roles | `manage_roles` | ロールの作成・付与・剥奪・削除とチャンネル権限の設定 |
| View Audit Log | `view_audit_log` | Discord 監査ログイベントの受信 |
| Connect | `connect` | CTF 用 VC の接続許可の設定 |
| Speak | `speak` | CTF 用 VC の発言許可の設定 |
| Video | `stream` | CTF 用 VC の配信許可の設定 |

権限上書きに使う権限は、チャンネル作成時は Guild で、archive 時は Guild または親カテゴリで Bot 自身が保持する必要がある（[チャンネル作成](https://docs.discord.com/developers/resources/guild#create-guild-channel)、[チャンネル変更](https://docs.discord.com/developers/resources/channel#modify-channel)）。
