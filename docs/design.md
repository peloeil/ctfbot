# 設計判断

このドキュメントはプロジェクトの設計思想と技術選定の理由を記録する。

## 分割方針

### 型の境界でモジュールを分割する

Discord オブジェクト（`guild`, `role`, `channel`）を受け取る関数と、プリミティブ型のみで動く関数を別モジュールに置く。後者は `asyncio.to_thread` 経由でも呼べるし、テストで Discord のモックが不要。

### `discord_ops.py` を ctf_team cog から分離する

Discord リソース操作（チャンネル作成、権限設定、archive 移動など）を standalone 関数に切り出す。関数シグネチャが依存を型で明示するため、暗黙の `self` 参照が発生しない。変更時に影響範囲が関数単位で閉じる。

### `alpacahack.py` は 1 ファイルに収める

スクレイパー、週次ロジック、cog を 1 ファイルにまとめる。約 400 行。「このファイルを修正して」で全体が完結する。

## 依存ルール

```
cog.py         → campaign.py, discord_ops.py, db.py, helpers.py
campaign.py    → db.py, errors.py, models.py
campaign.py    ✗ discord（import 禁止）
discord_ops.py → discord, helpers.py, models.py
discord_ops.py ✗ db.py（import 禁止）
alpacahack.py  → db.py, helpers.py
ctftime.py     → helpers.py
db.py          ✗ discord（import 禁止）
helpers.py     → discord

feature 間の相互 import は禁止（alpacahack ↔ ctftime ↔ ctf_team）。
```

`tests/test_architecture.py` で AST を使ってこのルールを検証している。

## 技術選定

### Python 3.14+

`pyproject.toml` の `requires-python = ">=3.14"` に準拠。

### discord.py 2.x

`commands.Bot` + `app_commands` でスラッシュコマンドを実装する。`command_prefix=commands.when_mentioned` でテキストコマンドは実質無効。`Intents.members = True` を有効にして `on_raw_reaction_add` でメンバー取得を行う。

### SQLite（WAL mode）

単一プロセスの bot で十分な規模。WAL mode で読み取りの並行性を確保する。blocking I/O は全て `asyncio.to_thread` 経由。

### requests（同期 HTTP）

外部 API 呼び出しは `asyncio.to_thread` で包むため、同期ライブラリで十分。aiohttp の複雑さを避ける。

### BeautifulSoup4

AlpacaHack のスクレイピング用。HTML パーサーとして `html.parser` を使用。

### uv

パッケージ管理・仮想環境管理。`uv sync --group dev` で開発依存を含むインストール。

## アーキテクチャ判断

### validation は例外ベース

`ServiceError` を raise し、cog で `try/except ServiceError` の 1 パターンで統一する。新しいバリデーション項目追加時も `raise ServiceError("...")` を書くだけで呼び出し側の変更が不要。

### Database を 1 クラスに集約する

2 テーブル・15 メソッド。全 SQL が 1 ファイルに集まるため、新しいクエリの追加先に迷わない。

### BotRuntime は Settings + Database のみ持つ

API クライアントは各 cog の `__init__` でローカル生成する。feature 追加時に runtime の変更が不要。

### 例外階層

| 例外 | 用途 | 処理 |
|---|---|---|
| `ServiceError` | ユーザー向けエラー。メッセージは日本語 | cog が catch → `send_interaction` で表示 |
| `RepositoryError` | DB 操作失敗 | ログに記録 |
| `ConflictError` | 一意制約違反（同名 campaign 等） | cog が catch → cleanup + エラー表示 |
| `ExternalAPIError` | 外部 API 呼び出し失敗 | ログに記録 + ユーザーにフォールバック応答 |
| `ConfigurationError` | 起動時の設定不備 | fail-fast（bot 起動しない） |
