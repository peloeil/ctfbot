# CTFBot

CTF 用の Discord bot

## 概要

このボットは、CTF（Capture The Flag）イベント向けのDiscord botです。主な機能として：

- 基本的なコマンド（ping、挨拶など）
- スラッシュコマンド（メッセージのピン留めなど）
- AlpacaHack CTFプラットフォームとの連携
- 定期的なタスク実行

## プロジェクト構造

```
.
├── README.md
├── pyproject.toml
├── src
│   ├── bot
│   │   ├── __init__.py               # ボット作成と実行関数
│   │   ├── config.py                 # 設定管理
│   │   ├── cogs_loader.py            # Cogsローダー
│   │   ├── cogs                      # コマンドモジュール
│   │   │   ├── alpacahack.py         # AlpacaHack関連コマンド
│   │   │   ├── basic_commands.py     # 基本コマンド
│   │   │   ├── manage_cogs.py        # Cog管理コマンド
│   │   │   ├── slash_commands.py     # スラッシュコマンド
│   │   │   └── tasks_loop.py         # 定期実行タスク
│   │   ├── db                        # データベース関連
│   │   │   └── database.py           # DB操作ユーティリティ
│   │   ├── services                  # 外部サービス連携
│   │   │   └── alpacahack_service.py # AlpacaHackスクレイピング
│   │   └── utils                     # ユーティリティ
│   │       └── helpers.py            # ヘルパー関数
│   └── main.py                       # エントリーポイント
└── uv.lock
```

## 開発準備

### Discord Bot の設定

1. 自分が管理者で他の人に迷惑のかからない discord サーバー(自分のみがメンバーのサーバーなど)を用意してください。
2. Discord Developers Portal で discord bot を作成し、好きな名前をつけます。
3. `cp .env.example .env` とし、`.env` 内の `DISCORD_TOKEN` を実際のトークン文字列で置き換えてください。
4. `BOT_CHANNEL_ID` を bot の自動メッセージを流すチャンネル ID にセットしてください。
5. このファイルは絶対に commit に含めないでください。

### Discord Bot の権限設定

1. PUBLIC BOT を uncheck してください。
2. Privileged Gateway Intents は、MESSAGE CONTENT INTENT を有効にしてください。
3. Scope は bot にしてください。
4. 必要な BOT_PERMISSIONS は以下の通りです：
   * GENERAL PERMISSIONS
     * View Channels
   * TEXT PERMISSIONS
     * Send Messages
     * Manage Messages
   * VOICE PERMISSIONS
     * なし

### 環境セットップ

1. UV パッケージマネージャをインストールします：
   ```
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. 依存関係をインストールします：
   ```
   uv sync --extra dev
   source .venv/bin/activate
   ```

3. ボットを実行します：
   ```
   python src/main.py
   ```

または、仮想環境を明示的に起動せずに直接実行することもできます：
   ```
   uv run src/main.py
   ```

## コード品質管理

このプロジェクトでは、コード品質を維持するために ruff を使用しています。

### コードフォーマット

コードのフォーマットには ruff format を使用します：

```
ruff format src/ tests/
```

### リンティング

コードのリンティングには ruff check を使用します：

```
ruff check src/ tests/
```

自動修正可能な問題を修正するには：

```
ruff check --fix src/ tests/
```

## 機能追加方法

機能追加は基本的に `./src/bot/cogs` 以下のファイルを編集するか、新しいcogを作成することで可能です。

新しい cogs を作る場合は、`./src/bot/cogs_loader.py` 内の extensions リストに追加する必要があります。

## PR のテスト方法

`{num}` を PR 番号で、`{test}` を好きな文字列で置き換えてください。

```
git fetch origin refs/pull/{num}/head:{test}
git checkout {test}
uv sync
source .venv/bin/activate
python src/main.py
```

## 開発ガイドライン

- main ブランチは PR 経由の merge でしか変更できません
- PR を merge するには1人以上の review が必須です
- コードスタイルは ruff を使用して一貫性を保ち、型ヒントを使用してください
- エラーハンドリングを適切に行い、ログを活用してください
- 設定は config.py で一元管理してください
- PR を提出する前に必ず `ruff format` と `ruff check` を実行してください
