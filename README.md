# CTFBot

CTF サーバー向けの Discord bot です。

## 主な機能

- **CTFtime 通知** — 近日開催の CTF イベントを定期通知 / `/ctftime` で手動取得
- **CTF 募集管理** — `/ctfteam open|list|close|archive` で参加者募集からアーカイブまで
- **AlpacaHack 連携** — `/alpaca add|del|list|solve` でユーザー管理と週次 solve 集計
- **times チャンネル** — `/times create` でカテゴリ配下にチャンネルを作成
- **ユーティリティ** — `/help`, `/perms`
- **一時的な管理者昇格** — `/sudo`, `/unsudo` で期限付きロールを管理
- **Discord 監査ログ保存** — Discord の監査ログエントリを DB に保存
- **接続状態通知** — Bot の接続・切断をステータスチャンネルへ通知

## Quick Start

```bash
uv sync --group dev  # 開発ツール込み。本番運用は uv sync で可
cp .env.example .env
# .env を編集（下記「環境変数」参照）
uv run python src/main.py
```

## 環境変数

必須は `DISCORD_TOKEN`・`GUILD_ID`・`CTF_TEAM_CATEGORY_ID`・`CTF_TEAM_ARCHIVE_CATEGORY_ID`・`CTF_TEAM_ROLE_CHANNEL_ID` の 5 つです。全項目の用途・型・必須性・デフォルト・検証規則は `docs/data-contracts.md`「設定契約」を参照してください（`.env.example` は同表と同期しています）。

## Discord の設定

### Developer Portal

1. **Installation** — `Guild Install` を有効にし、`Install Link` を `None` に設定
2. **OAuth2** — scope に `bot` と `applications.commands` を選択し、生成された URL から Bot を招待
3. **Bot** — 公開 Bot をオフにし、`Server Members Intent` を有効化

### Bot に必要な権限

- `View Channel`
- `Send Messages`
- `Send Messages in Threads`
- `Embed Links`
- `Read Message History`
- `Add Reactions`
- `Manage Channels`
- `Manage Roles`
- `View Audit Log`

`Manage Roles` を使うため、Bot のロールは操作対象のロールより上位に配置してください。

### サーバー側の準備

- 募集メッセージの投稿先テキストチャンネルを作成し、その ID を `CTF_TEAM_ROLE_CHANNEL_ID` に設定してください（無いと `/ctfteam open` が失敗します）
- `/times create` を使う場合は、作成先カテゴリを作成し、その ID を `TIMES_CATEGORY_ID` に設定してください

## 運用メモ

- スラッシュコマンドは `GUILD_ID` の guild にのみ登録されます（グローバル登録なし）。起動時に同期され、即時反映されます
- `/ctfteam open` で作成される discussion / voice チャンネルは `CTF_TEAM_CATEGORY_ID` のカテゴリ配下に作成されます
- `/ctfteam archive` は discussion チャンネルを `CTF_TEAM_ARCHIVE_CATEGORY_ID` のカテゴリに移動します
- DB スキーマはバージョン管理されており、旧バージョンの DB は起動時に自動 migration されます。起動を拒否するのは、バージョン管理外の DB（バージョン 0 でテーブルあり）・bot より新しいバージョンの DB・migration path の無いバージョンの DB です（契約の正本は `docs/data-contracts.md`）
