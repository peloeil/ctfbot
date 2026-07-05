# 設計判断

このドキュメントはプロジェクトの設計思想と技術選定の理由を記録する。

## 分割方針

### 型の境界でモジュールを分割する

Discord 非依存ロジックを独立してテスト・再利用する必要がある場合は別モジュールに分ける。単一ファイルで完結する小規模 feature（alpacahack, ctftime, times 等）では同居してよい。分割の判断基準は行数ではなく「Discord のモック無しでテストしたいか」「他の feature から再利用するか」。

### `discord_ops.py` を ctf_team cog から分離する

Discord リソース操作（チャンネル作成、権限設定、archive 移動など）を standalone 関数に切り出す。関数シグネチャが依存を型で明示するため、暗黙の `self` 参照が発生しない。変更時に影響範囲が関数単位で閉じる。

### `alpacahack.py` は 1 ファイルに収める

スクレイパー、週次ロジック、cog を 1 ファイルにまとめる。約 400 行。「このファイルを修正して」で全体が完結する。

## 依存ルール

```
cog.py         → campaign.py, discord_ops.py, db.py, helpers.py, runtime.py
campaign.py    → db.py, errors.py, models.py
campaign.py    ✗ discord（import 禁止）
discord_ops.py → discord, helpers.py, models.py
discord_ops.py ✗ db.py（import 禁止）
alpacahack.py  → db.py, helpers.py, runtime.py
ctftime.py     → helpers.py, runtime.py
db.py          → features/<feature>/models.py（許可。ただし models.py は discord import 禁止）
db.py          ✗ discord（import 禁止）
helpers.py     → discord, runtime.py
runtime.py     → config.py, db.py

feature 間の相互 import は禁止（alpacahack ↔ ctftime ↔ ctf_team）。
```

`tests/test_architecture.py` で AST を使ってこのルールを検証している。

コア層の db.py が feature の models.py に依存するのは「Database を 1 クラスに集約する」方針の意図的な帰結。この辺を安全に保つため、feature の models.py は discord に依存しない純粋なデータモデルに限定する（アーキテクチャテストで検証）。

## 技術選定

### Python 3.14+

`pyproject.toml` の `requires-python = ">=3.14"` に準拠。

### discord.py 2.x

`commands.Bot` + `app_commands` でスラッシュコマンドを実装する。`command_prefix=commands.when_mentioned` でテキストコマンドは実質無効。`Intents.members = True` を有効にして `on_raw_reaction_add` でメンバー取得を行う。

### SQLite（WAL mode）

単一プロセスの bot で十分な規模。WAL mode で読み取りの並行性を確保する。blocking I/O は全て `asyncio.to_thread` 経由。

スキーマ変更は `db.py` の `_MIGRATIONS`（`{from_version: SQL スクリプト}`）に version N → N+1 の移行 SQL を登録する方式。起動時に `user_version` から `CURRENT_SCHEMA_VERSION` まで順に適用する。移行パスが無い version の DB は起動拒否（fail-fast）。移行スクリプトは再実行に耐える形（`IF NOT EXISTS` 等）で書く — スクリプト適用と version 更新の間にクラッシュすると再実行されるため。

### requests（同期 HTTP）

外部 API 呼び出しは `asyncio.to_thread` で包むため、同期ライブラリで十分。aiohttp の複雑さを避ける。

### BeautifulSoup4

AlpacaHack のスクレイピング用。HTML パーサーとして `html.parser` を使用。

### uv

パッケージ管理・仮想環境管理。`uv sync --group dev` で開発依存を含むインストール。

## アーキテクチャ判断

### validation は例外ベース

複数ステップの検証は `ServiceError` を raise し、cog で `try/except ServiceError` の 1 パターンで統一する。新しいバリデーション項目追加時も `raise ServiceError("...")` を書くだけで呼び出し側の変更が不要。単純な Discord 入力チェック（空文字・guild 存在確認など）は cog 内で直接応答してよい。

### Database を 1 クラスに集約する

2 テーブル・15 メソッド。全 SQL が 1 ファイルに集まるため、新しいクエリの追加先に迷わない。

### BotRuntime は Settings + Database のみ持つ

API クライアントは各 cog の `__init__` でローカル生成する。feature 追加時に runtime の変更が不要。

`BotRuntime` / `get_runtime` は `runtime.py` に置く（app.py ではなく）。feature と helpers が bot アプリ全体（CTFBot クラス、signal 処理）に依存せず、runtime だけに依存できる。helpers.log_audit も型安全に runtime へアクセスできる。

### 定期ループから呼ばれる処理は冪等にする

毎分ループ（close/archive 等）は失敗した項目を翌分また拾う。したがって:

- **非冪等な副作用（通知・スナップショット送信）は、DB の状態遷移が確定した後に置く。** 状態遷移前に置くと、後続ステップの恒久的失敗時に毎分再送される
- **対象が既に存在しない（`discord.NotFound`）操作は成功扱いにする。** 「消すべきものが既に無い」「編集すべきメッセージが既に無い」は目的達成と同義
- 通知送信自体の失敗は状態を巻き戻さない（DB が正）

### 週次通知の実行時刻は start 前に設定する

`tasks.loop` は相対間隔（`hours=` 等）だと最初のイテレーションを即時実行する。`change_interval(time=...)` は次イテレーションからしか効かないため、`before_loop` 内で呼ぶと bot 再起動時に即時 1 回 + 指定時刻に 1 回の二重実行になる。時刻指定は cog の `__init__` で `.start()` より前に `change_interval(time=...)` を呼んで行う。

### 認可ポリシー

このボットは招待制の信頼されたメンバーのみのサーバーで運用する前提のため、コマンドは原則全メンバーに開放する。例外:

- `/ctfteam close|archive` — 作成者 または `manage_guild` 権限保持者のみ（他人の募集を壊せないように）
- リソース量の暴走はコマンド側の上限で防ぐ（`/ctfteam open` は 1 人 active 5 件まで、`/times create` は 1 回 10 チャンネルまで）

### 募集作成は Discord 先行・DB 後行

`/ctfteam open` は Discord リソース（ロール・チャンネル・メッセージ）を作成してから DB に記録する。例外時は `cleanup_resources` で補償削除する。DB insert 前にプロセスがクラッシュした場合は孤児リソースが残り自動回収されない — 発生頻度が低いため手動掃除で許容する（意図的なトレードオフ）。

### 例外階層

| 例外 | 用途 | 処理 |
|---|---|---|
| `ServiceError` | ユーザー向けエラー。メッセージは日本語 | cog が catch → `send_interaction` で表示 |
| `RepositoryError` | DB 操作失敗 | ログに記録 |
| `ConflictError` | 一意制約違反（同名 campaign 等） | cog が catch → cleanup + エラー表示 |
| `ExternalAPIError` | 外部 API 呼び出し失敗 | ログに記録 + ユーザーにフォールバック応答 |
| `ConfigurationError` | 起動時の設定不備 | fail-fast（bot 起動しない） |
