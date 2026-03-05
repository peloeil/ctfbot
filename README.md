# CTFBot

CTF サーバー向け Discord bot です。  
公開運用を前提に、設定と必須 Cog ロードの fail-fast、ログ統一、非同期タスクの安定運用を重視した構成に再設計しています。

## 主な機能

- CTFtime の定期通知（週次）と手動通知コマンド `/ctf`
- CTF ロール募集管理（`/ctf-role create|list|close`、`#role` で募集、`ctf` カテゴリへ専用チャンネル作成、リアクション連動ロール付与、終了/アーカイブ自動処理、ロール色指定）
- times カテゴリのチャンネル作成 (`/create-times`)
- AlpacaHack の週次 solve サマリ通知（登録ユーザー対象、毎週日曜）
- AlpacaHack ユーザー管理 (`/alpaca_add`, `/alpaca_del`, `/alpaca_list`)
- AlpacaHack スコア表示 (`/alpaca_solve`)
- Slash コマンド管理 (`/help`, `/sync`, `/load`, `/unload`, `/reload`, `/pin`, `/unpin`, `/perms`, `/create-times`)
- Bot の接続状態通知（任意）

## 参加ガイド

- 初めて開発に参加する場合は [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md) を先に読んでください。
- 機能追加の手順、実装例、テスト方針、PR 前チェックをまとめています。

## ディレクトリ構成

```text
src/
  bot/
    __init__.py              # パッケージ定義
    app.py                   # Bot 生成と起動
    runtime.py               # Runtime 組み立て
    runtime_providers.py     # 依存注入用 provider 群
    config.py                # 環境変数の読み込みとバリデーション
    errors.py                # 例外階層
    discord_gateway.py       # Discord channel 解決の共通化
    cogs_loader.py           # 本番 cogs のロード
    features/                # 機能単位（縦割り）
      alpacahack/
        cog.py
        usecase.py
        service.py
        repository.py
      ctf_roles/
        cog.py
        usecase.py
        service.py
        repository.py
      ctftime/
        cog.py
        usecase.py
        service.py
    cogs/
      manage_cogs.py
      message_tools.py
      perms_debug.py
      times_channels.py
    db/
      connection.py          # 接続管理
      migrations.py          # スキーマ適用
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
2. Privileged Gateway Intents は `MESSAGE CONTENT INTENT` と `SERVER MEMBERS INTENT` を有効にします。
3. OAuth2 の Scope は `bot`（必要なら `applications.commands` も）を選択します。
4. bot アカウントに付与する権限の目安:
   - `View Channels`
   - `Send Messages`
   - `Manage Messages`（`/pin` `/unpin` の実行に必要）
   - `Manage Roles`（`/ctf-role create` の role 作成/削除に必要）
   - `Manage Channels`（`/ctf-role create` と `/create-times` のチャンネル作成に必要）
   - `Add Reactions`（`/ctf-role create` で募集メッセージにリアクションを付けるために必要）

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

## チーム開発ルール

1. 依存方向は `cog -> usecase -> service/repository -> db` に固定します。
2. `src/bot/cogs/` から `src/bot/db/` を直接 import しません。機能本体は `src/bot/features/` で実装します。
3. 新機能は `src/bot/features/<feature>/` に追加します。
4. 例外は `bot.errors` の型を使って層ごとに扱いを明確にします。
5. 境界違反は `tests/test_architecture.py` で検出されます。

## CI

GitHub Actions の `CI` ワークフローで以下を実行します。

1. `uv run ruff check src tests`
2. `uv run ty check`
3. `uv run python -m unittest discover -s tests -v`

## 開発時の反映手順（bot を止めない運用）

1. Cog ファイルを変更したら `/reload name:<cog名>` を実行する
2. Slash コマンド定義を変更したら `/reload` の後に `/sync` を実行する
3. `config.py`、`.env`、共通モジュールの変更時は bot を再起動する

## 権限モデルのメモ（このサーバー向け）

1. `/pin` と `/unpin` は、実行ユーザーに `Manage Messages` は不要  
実行対象チャンネルを「閲覧 + 投稿」できれば実行可能です。
2. `/ctf` も同様に、実行チャンネルを「閲覧 + 投稿」できれば実行可能です。
3. `/sync`, `/load`, `/unload`, `/reload` は `Manage Server` 権限が必要です。
4. bot アカウント側には、`/pin` `/unpin` を動かすために `Manage Messages` 権限が必要です。
5. `/ctf-role create` には、bot アカウント側で `Manage Roles` / `Manage Channels` / `Add Reactions` が必要です。
6. `/create-times` には、bot アカウント側で `times` カテゴリに対する `Manage Channels` が必要です。

## 新しい機能を足すとき

1. `src/bot/features/<feature>/` に `cog.py`, `usecase.py`, `service.py`（必要なら `repository.py`, `models.py`）を追加する。
2. 起動時に自動ロードしたい場合は `src/bot/cogs_loader.py` の `DEFAULT_EXTENSIONS` に追加する。
3. Slash コマンドを追加した場合は `/sync` で反映する。
4. `tests/` にユニットテストと `tests/test_architecture.py` の境界ルールに沿ったテストを追加する。
