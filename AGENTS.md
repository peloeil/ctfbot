# AGENTS.md

このプロジェクトは **Claude が設計し、Codex が実装する** ワークフローで開発されている。

## 情報の優先順位

**プロンプトでの指示 > AGENTS.md > docs/**

- プロンプトが実装対象として指定した仕様書（`docs/features/*.md` 等）はプロンプトの一部（規範）として扱う
- それ以外の `docs/` は既存機能の仕様確認に使う参考資料であり、新規実装の制約ではない
- 既存ドキュメントと矛盾する変更を指示された場合はプロンプトを優先すること

## 仕様リファレンス

| 調べたいこと | ファイル |
|---|---|
| 設計思想・分割方針・技術選定理由 | `docs/design.md` |
| 設定（環境変数）・データモデル・DB スキーマ・Database API の契約 | `docs/data-contracts.md` |
| GitHub CI の仕様 | `docs/ci.md` |
| bot 共通の応答・通知挙動（エラーハンドラ・監査ログ・状態通知） | `docs/core.md` |
| CTF 募集管理の仕様 | `docs/features/ctf-team.md` |
| CTFtime 通知の仕様 | `docs/features/ctftime.md` |
| AlpacaHack 連携の仕様 | `docs/features/alpacahack.md` |
| times チャンネルの仕様 | `docs/features/times.md` |
| ユーティリティコマンドの仕様 | `docs/features/utility.md` |
| Discord 監査ログ保存の仕様 | `docs/features/audit-log.md` |
| 一時的な管理者昇格 (sudo) の仕様 | `docs/features/sudo.md` |
| セットアップ・環境変数・Discord 設定 | `README.md` |

## アーキテクチャ制約

実装時に必ず守ること。制約 2〜6（import 境界）は `tests/test_architecture.py` で静的に検証されている。それ以外はレビューでのみ担保される。

1. **型の境界でモジュールを分割する** — Discord 非依存ロジックを独立してテスト・再利用する必要がある場合は別モジュールに分ける。単一ファイルで完結する小規模 feature は同居してよい
2. **`db.py` は discord を import しない** — feature からの import は `models.py` のみ許可
3. **feature の `models.py` は discord を import しない** — `db.py` が import するため純粋なデータモデルに限定
4. **`campaign.py` は discord を import しない**
5. **`discord_ops.py` は `bot.db` を import しない**
6. **feature 間の相互 import 禁止** — `src/bot/features/` 直下のすべての feature が対象。互いを import しない
7. **BotRuntime は Settings + Database のみ** — `bot/runtime.py` に定義。API クライアントは各 cog の `__init__` でローカル生成する
8. **バリデーションは例外ベース** — 複数ステップの検証は `ServiceError` を raise し cog で `try/except ServiceError` で統一。単純な Discord 入力チェック（空文字・guild 存在確認など）は cog 内で直接応答してよい
9. **Database は 1 クラスに集約** — 全テーブル・全 SQL が `db.py` に収まる
10. **async context の blocking I/O は `asyncio.to_thread`** — イベントループ上で実行される同期 I/O（DB アクセス、HTTP リクエスト）は必ずスレッド委譲。イベントループ外（起動時の初期化、同期テスト）は対象外
11. **定期ループから呼ばれる処理は冪等にする** — 非冪等な副作用（通知送信）は DB の状態遷移確定後に置く。`discord.NotFound` は成功扱い（docs/design.md 参照）

## コーディング規約

- **Linter**: `ruff` — `line-length = 88`、ルール `E, F, I, W, N, UP, B, C4, SIM, RUF`
- **Type checker**: `ty` — `python-version = "3.14"`、ルート `./src`
- **dataclass**: `frozen=True, slots=True` を標準で付ける
- **言語**: コード・変数名は英語。ユーザー向けメッセージ（Discord に送信するもの）は日本語。例外は、ユーザーに表示しない内部例外メッセージ（`docs/design.md` 例外階層）と、外部データ欠落時の代替表示値（例: CTFtime の `"Untitled"`。`docs/features/ctftime.md`）
- **例外階層**: `BotError > ConfigurationError | RepositoryError (> ConflictError) | ServiceError (> ExternalAPIError)`

## 情報の書き分け原則（必須）

**コードには How、テストコードには What、コミットログには Why、コードコメントには Why not。**

- **コード (How)**: 処理の流れは命名と分割だけで追えるようにする。コメントで補わない
- **テスト (What)**: テスト名は振る舞い仕様を記述する（例: `test_retry_after_close_does_not_resend_snapshot`）。assert は期待値そのものを検証し、型だけを検証して終わらない（状態別戻り値型の契約確認としての `assertIsInstance` は可）
- **コミットログ (Why)**: subject は変更内容の要約、本文に「何が問題で、なぜこの変更か」を書く
- **コメント (Why not)**: 原則書かない。素直な書き方をあえて避けた箇所（一見バグに見える処理、マジックナンバーの根拠、意味のある実行順序など）のみ、理由を 1 行で書く

## 実装パターン

新しい cog を追加するときの典型的な手順。既存の `features/times.py` が最小の参考例（settings のみ使用）、`features/alpacahack.py` が runtime・DB・定期タスクを使う例。

1. `src/bot/features/` にファイルを作成する
2. `commands.Cog`（単発コマンド）または `commands.GroupCog`（サブコマンド群）を継承したクラスを定義する
3. settings / db が必要なら `__init__` で `get_runtime(bot)` を呼び、`self.settings` / `self.db` を保持する（不要なら `self.bot` のみでよい）
4. 外部 API クライアントが必要なら `__init__` でインスタンスを作る（BotRuntime には追加しない）
5. ファイル末尾に `async def setup(bot: commands.Bot) -> None:` を必ず置く
6. `cogs_loader.py` の `DEFAULT_EXTENSIONS` にモジュールパスを追加する
7. `tests/test_architecture.py` の `feature_modules` に新 feature のモジュールパスを追加する
8. DB テーブルが必要なら `db.py` の `_SCHEMA_DDL` に DDL を追加し、`CURRENT_SCHEMA_VERSION` をインクリメントし、`_MIGRATIONS` に旧 version からの移行 SQL を追加する。移行 SQL は再実行に耐える形（`IF NOT EXISTS`・冪等な UPDATE 等）で書き、`docs/data-contracts.md` を同時に更新する

```python
# 最小の cog テンプレート
import discord
from discord import app_commands
from discord.ext import commands

from bot.helpers import send_interaction
from bot.runtime import get_runtime


class MyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        runtime = get_runtime(bot)
        self.bot = bot
        self.settings = runtime.settings
        self.db = runtime.db

    @app_commands.command(name="mycommand", description="説明")
    async def my_command(self, interaction: discord.Interaction) -> None:
        await send_interaction(interaction, "応答テキスト")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyCog(bot))
```

settings / db が不要な cog は `get_runtime` と `self.settings` / `self.db` の行を省く。

## 検証

Codex が検証できるのは以下の 3 つ。すべてパスさせてから完了とすること。

```bash
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
uv run ty check
uv run python -m unittest discover -s tests -v
```

**bot の実行（`uv run python src/main.py`）は行わないこと。** Discord トークンが必要であり、実際の Discord 動作確認は人間が行う。
