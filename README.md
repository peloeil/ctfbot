# CTFBot

CTF サーバー向け Discord bot です。  
公開運用を前提に、設定の fail-fast、ログ統一、非同期タスクの安定運用を重視した構成に再設計しています。

## 主な機能

- CTFtime の定期通知（週次）と手動通知コマンド `!ctf`
- AlpacaHack の週次 solve サマリ通知（登録ユーザー対象）
- AlpacaHack ユーザー管理 (`!add_alpaca`, `!del_alpaca`, `!show_alpaca`)
- AlpacaHack スコア表示 (`!show_alpaca_score`)
- Slash コマンド管理 (`/sync`, `/load`, `/unload`, `/reload`, `/pin`, `/unpin`)
- Bot の接続状態通知（任意）

## ディレクトリ構成

```text
src/
  bot/
    __init__.py              # Bot 生成と起動
    config.py                # 環境変数の読み込みとバリデーション
    cogs_loader.py           # 本番 cogs のロード
    cogs/
      alpacahack.py
      ctftime_notifications.py
      manage_cogs.py
      slash_commands.py
    db/
      database.py
    services/
      alpacahack_service.py
      ctftime_service.py
    utils/
      helpers.py
  main.py                    # エントリポイント
```

## セットアップ

### Discord Bot の設定（従来手順）

1. 自分が管理者で、他の人に迷惑のかからない Discord サーバー（自分のみがメンバーのサーバーなど）を用意します。
2. Discord Developers Portal で Discord bot を作成し、名前を設定します。
3. `cp .env.example .env` を実行し、`.env` 内の `DISCORD_TOKEN` を実際のトークンに置き換えます。
4. `BOT_CHANNEL_ID` を bot の定期メッセージ送信先チャンネル ID に設定します。
5. `.env` は commit に含めないでください。

### Discord Bot の権限設定（従来手順）

1. Bot 公開設定（Public Bot）は運用方針に応じて設定します。
2. Privileged Gateway Intents は `MESSAGE CONTENT INTENT` を有効にします。
3. OAuth2 の Scope は `bot`（必要なら `applications.commands` も）を選択します。
4. bot アカウントに付与する権限の目安:
   - `View Channels`
   - `Send Messages`
   - `Manage Messages`（`/pin` `/unpin` の実行に必要）

### ローカル実行手順

1. 依存をインストール

```bash
uv sync --group dev
```

2. 環境変数を設定

```bash
cp .env.example .env
```

必須:

- `DISCORD_TOKEN`

主要オプション:

- `BOT_CHANNEL_ID`: 定期通知先チャンネル
- `BOT_STATUS_CHANNEL_ID`: 起動/再接続/終了通知先チャンネル（任意）
- `TIMEZONE`: 例 `Asia/Tokyo`
- `DATABASE_PATH`: SQLite ファイルパス

3. 実行

```bash
uv run python src/main.py
```

## 開発コマンド

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check
uv run python -m unittest discover -s tests -v
```

## 開発時の反映手順（bot を止めない運用）

1. Cog ファイルを変更したら `/reload name:<cog名>` を実行する
2. Slash コマンド定義を変更したら `/reload` の後に `/sync` を実行する
3. `config.py`、`.env`、共通モジュールの変更時は bot を再起動する

## 権限モデルのメモ（このサーバー向け）

1. `/pin` と `/unpin` は、実行ユーザーに `Manage Messages` は不要  
実行対象チャンネルを「閲覧 + 投稿」できれば実行可能です。
2. `!ctf` も同様に、実行チャンネルを「閲覧 + 投稿」できれば実行可能です。
3. `/sync`, `/load`, `/unload`, `/reload` は `Manage Server` 権限が必要です。
4. bot アカウント側には、`/pin` `/unpin` を動かすために `Manage Messages` 権限が必要です。

## 新しい機能を足すとき

1. `src/bot/cogs/` に新しい cog を追加する。
2. 起動時に自動ロードしたい場合は `src/bot/cogs_loader.py` の `DEFAULT_EXTENSIONS` に追加する。
3. Slash コマンドを追加した場合は `/sync` で反映する。
4. 追加した機能に対応するテストを `tests/` に追加する。
