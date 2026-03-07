# CTFBot

CTF サーバー向けの Discord bot です。公開運用を前提に、設定の fail-fast、必須 cog の確実なロード、安定した非同期運用を重視しています。

## 主な機能

- CTFtime の定期通知と手動実行 `/ctftime`
- CTF 参加募集の管理 `/ctfteam open|list|close`
- `times` カテゴリのチャンネル作成 `/times create`
- AlpacaHack ユーザー管理と週次 solve 集計 `/alpaca add|del|list|solve`
- 運用用 slash command `/help`, `/cog`, `/message`, `/perms`
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

## Discord 側の前提

- `MESSAGE CONTENT INTENT` を有効にする
- `SERVER MEMBERS INTENT` を有効にする
- 全機能を使う場合、bot には少なくとも次を付与する
  - `View Channel`（チャンネルを表示）
  - `Send Messages`（メッセージを送信）
  - `Send Messages in Threads`（スレッド内でメッセージを送信）
  - `Read Message History`（メッセージ履歴を読む）
  - `Add Reactions`（リアクションを追加）
  - `Pin Messages`（メッセージをピン留め）
  - `Manage Roles`（ロール管理）
  - `Manage Channels`（チャンネルの管理）
- `Manage Roles` を使う機能のために、bot のロールは作成・付与対象のロールより上位に置く

## 運用メモ

- CTFtime の通知先は `BOT_CHANNEL_ID`
- AlpacaHack の週次通知先は `ctf` カテゴリ配下の `#alpacahack`
- 接続状態通知は `BOT_STATUS_CHANNEL_ID` を設定した場合のみ送信
- 設定項目の一覧は `.env.example` と `src/bot/config.py` を参照

## ドキュメントの役割

- `README.md`
  セットアップ、運用前提、起動方法
- `docs/DEVELOPMENT_GUIDE.md`
  人間向けの設計と開発手順
- `AGENTS.md`
  Codex などの coding agent 向けの実装規約と検証手順
