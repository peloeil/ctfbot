# CTFBot

CTF サーバー向けの Discord bot です。

## 主な機能

- **CTFtime 通知** — 近日開催の CTF イベントを定期通知 / `/ctftime` で手動取得
- **CTF 募集管理** — `/ctfteam open|list|close|archive` で参加者募集からアーカイブまで
- **AlpacaHack 連携** — `/alpaca add|del|list|solve` でユーザー管理と週次 solve 集計
- **times チャンネル** — `/times create` でカテゴリ配下にチャンネルを一括作成
- **ユーティリティ** — `/help`, `/perms`
- **一時的な管理者昇格** — `/sudo`, `/unsudo` で期限付きロールを管理
- **監査ログ保存** — Discord の監査ログエントリを DB に保存
- **接続状態通知** — Bot の接続・切断をステータスチャンネルへ通知

## Quick Start

```bash
uv sync --group dev
cp .env.example .env
# .env を編集（下記「環境変数」参照）
uv run python src/main.py
```

## 環境変数

`.env.example` に全項目の一覧があります。

| 変数 | 必須 | 説明 |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Bot トークン |
| `CTF_TEAM_CATEGORY_ID` | Yes | 募集チャンネルを作成するカテゴリ ID |
| `CTF_TEAM_ARCHIVE_CATEGORY_ID` | Yes | アーカイブ先カテゴリ ID |
| `BOT_CHANNEL_ID` | | コマンド実行ログの送信先（0 で無効） |
| `BOT_STATUS_CHANNEL_ID` | | 接続状態通知の送信先（0 で無効） |
| `CTFTIME_CHANNEL_ID` | | CTFtime 通知の送信先（0 で無効） |
| `ALPACAHACK_CHANNEL_ID` | | AlpacaHack 通知の送信先（0 で無効） |
| `ADMIN_ROLE_ID` | | `/sudo` で一時付与する管理者ロール ID（`SUDOER_ROLE_ID` とセットで設定。片方だけだと起動拒否） |
| `SUDOER_ROLE_ID` | | `/sudo` の実行を許可するロール ID（同上） |
| `SUDO_DURATION_MINUTES` | | 昇格の有効時間（デフォルト `30` 分） |
| `TIMEZONE` | | タイムゾーン（デフォルト `Asia/Tokyo`） |
| `LOG_LEVEL` | | ログレベル（デフォルト `INFO`） |
| `DATABASE_PATH` | | SQLite DB パス（デフォルト `ctfbot.db`） |

その他スケジュール関連の設定（`ALPACAHACK_SOLVE_TIME`, `CTFTIME_NOTIFICATION_TIME` 等）は `.env.example` を参照してください。

## Discord の設定

### Developer Portal

1. **Installation** — `Guild Install` を有効にし、`Install Link` を `None` に設定
2. **OAuth2** — scope に `bot` と `applications.commands` を選択し、生成された URL から Bot を招待
3. **Bot** — 公開 Bot をオフにし、`Server Members Intent` を有効化

### Bot に必要な権限

- `View Channel`
- `Send Messages`
- `Send Messages in Threads`
- `Read Message History`
- `Add Reactions`
- `Manage Channels`
- `Manage Roles`
- `View Audit Log`

`Manage Roles` を使うため、Bot のロールは操作対象のロールより上位に配置してください。

## 運用メモ

- `/ctfteam open` で作成される discussion / voice チャンネルは `CTF_TEAM_CATEGORY_ID` のカテゴリ配下に作成されます
- `/ctfteam archive` は discussion チャンネルを `CTF_TEAM_ARCHIVE_CATEGORY_ID` のカテゴリに移動します
- DB スキーマはバージョン管理されており、旧バージョンの DB は起動時に自動 migration されます。起動を拒否するのは、バージョン管理外の DB（バージョン 0 でテーブルあり）・bot より新しいバージョンの DB・migration path の無いバージョンの DB です
