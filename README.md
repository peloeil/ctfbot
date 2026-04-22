# CTFBot

CTF サーバー向けの Discord bot です。公開運用を前提に、設定の fail-fast、必須 cog の確実なロード、安定した非同期運用を重視しています。

## 主な機能

- CTFtime の定期通知と手動実行 `/ctftime`
- CTF 参加募集の管理 `/ctfteam open|list|close|archive`
- `times` カテゴリのチャンネル作成 `/times create`
- AlpacaHack ユーザー管理と週次 solve 集計 `/alpaca add|del|list|solve`
- 運用用 slash command `/help`, `/perms`
- Bot の接続状態通知

## Quick Start

1. 依存をインストールします。

```bash
uv sync --group dev
```

2. 環境変数を用意します。

```bash
cp .env.example .env
```

3. 最低限 `DISCORD_TOKEN` を設定します。

4. bot を起動します。

```bash
uv run python src/main.py
```

## Discord Developer Portal の設定

### 1. Installation

- `Guild Install` を有効にします
- `User Install` は不要です
- `Install Link` を `None` にします

### 2. OAuth2

- scope として `bot` と `applications.commands` を使います
- 生成された URL から bot をインストールします

### 3. Bot

- 公開 Bot をオフにします。
- Bot token を発行して `.env` の `DISCORD_TOKEN` に設定します
- `Server Members Intent` を有効にします

## Discord 側の前提

- 全機能を使う場合、bot には少なくとも次を付与する
  - `Send Messages`（メッセージを送る）
  - `Send Messages in Threads`（Threadsでメッセージを送る）
  - `Read Message History`（メッセージ履歴を読む）
  - `View Channel`（チャンネルを表示）
  - `Manage Channels`（チャンネルの管理）
  - `Add Reactions`（リアクションを付ける）
  - `Manage Roles`（ロールの管理）
- `Manage Roles` を使う機能のために、bot のロールは作成・付与対象のロールより上位に置く

## 運用メモ

- CTFtime の通知先は `BOT_CHANNEL_ID`
  `/ctfteam open|close|archive`, `/times create`, `/alpaca add|del` のような write 系コマンドの実行履歴も同じチャンネルへ送信する
- AlpacaHack の週次通知先は `ctf` カテゴリ配下の `#alpacahack`
- 接続状態通知は `BOT_STATUS_CHANNEL_ID` を設定した場合のみ送信
- 設定項目の一覧は `.env.example` と `src/bot/config.py` を参照
- DB schema は current-only。schema version が current と一致しない DB は起動時に拒否される
- 旧 `ctf_role_campaign` を使っている DB は、bot 起動前に `python scripts/migrate_ctf_team_db.py <db_path> [--rename-to ctfbot.db]` を手動実行して current schema に変換する

## ドキュメントの役割

- `README.md`
  セットアップ、運用前提、起動方法
- `docs/DEVELOPMENT_GUIDE.md`
  人間向けの設計と開発手順
- `AGENTS.md`
  Codex などの coding agent 向けの実装規約と検証手順
