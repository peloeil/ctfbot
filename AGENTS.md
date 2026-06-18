# AGENTS.md

このプロジェクトは **Claude が設計し、Codex が実装する** ワークフローで開発されている。

## 情報の優先順位

**プロンプトでの指示 > AGENTS.md > docs/**

- `docs/` 以下は既存機能の仕様確認に使う参考資料であり、新規実装の制約ではない
- 新機能追加時にドキュメントと矛盾する場合はプロンプトの指示を優先すること

## 仕様リファレンス

| 調べたいこと | ファイル |
|---|---|
| 設計思想・分割方針・技術選定理由 | `docs/design.md` |
| CTF 募集管理の仕様 | `docs/features/ctf-team.md` |
| CTFtime 通知の仕様 | `docs/features/ctftime.md` |
| AlpacaHack 連携の仕様 | `docs/features/alpacahack.md` |
| times チャンネルの仕様 | `docs/features/times.md` |
| ユーティリティコマンドの仕様 | `docs/features/utility.md` |
| セットアップ・環境変数・Discord 設定 | `README.md` |

## アーキテクチャ制約

実装時に必ず守ること。`tests/test_architecture.py` で静的に検証されている。

1. **型の境界でモジュールを分割する** — Discord オブジェクトを受け取る関数と、プリミティブ型のみの関数は別モジュール
2. **`db.py` は discord を import しない**
3. **`campaign.py` は discord を import しない**
4. **`discord_ops.py` は `bot.db` を import しない**
5. **feature 間の相互 import 禁止** — `alpacahack`, `ctftime`, `times`, `utility`, `ctf_team` は互いを import しない
6. **BotRuntime は Settings + Database のみ** — API クライアントは各 cog の `__init__` でローカル生成する
7. **バリデーションは例外ベース** — `ServiceError` を raise し、cog で `try/except ServiceError` で統一
8. **Database は 1 クラスに集約** — 全テーブル・全 SQL が `db.py` に収まる
9. **blocking I/O は `asyncio.to_thread`** — DB アクセス、HTTP リクエストなど同期処理は必ずスレッド委譲

## コーディング規約

- **Linter**: `ruff` — `line-length = 88`、ルール `E, F, I, W, N, UP, B, C4, SIM, RUF`
- **Type checker**: `ty` — `python-version = "3.14"`、ルート `./src`
- **dataclass**: `frozen=True, slots=True` を標準で付ける
- **コメント**: 原則書かない。WHY が自明でない場合のみ 1 行
- **言語**: コード・変数名は英語。ユーザー向けメッセージ（Discord に送信するもの）は日本語
- **例外階層**: `BotError > ConfigurationError | RepositoryError (> ConflictError) | ServiceError (> ExternalAPIError)`

## 実装パターン

新しい cog を追加するときの典型的な手順。既存の `features/times.py` が最小の参考例。

1. `src/bot/features/` にファイルを作成する
2. `commands.Cog`（単発コマンド）または `commands.GroupCog`（サブコマンド群）を継承したクラスを定義する
3. `__init__` で `get_runtime(bot)` を呼び、`self.settings` / `self.db` を保持する
4. 外部 API クライアントが必要なら `__init__` でインスタンスを作る（BotRuntime には追加しない）
5. ファイル末尾に `async def setup(bot: commands.Bot) -> None:` を必ず置く
6. `cogs_loader.py` の `DEFAULT_EXTENSIONS` にモジュールパスを追加する
7. DB テーブルが必要なら `db.py` の `_SCHEMA_DDL` に DDL を追加し `CURRENT_SCHEMA_VERSION` をインクリメントする

```python
# 最小の cog テンプレート
import discord
from discord import app_commands
from discord.ext import commands

from bot.app import get_runtime
from bot.helpers import send_interaction


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

## 検証

Codex が検証できるのは以下の 3 つ。すべてパスさせてから完了とすること。

```bash
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
uv run ty check
uv run python -m unittest discover -s tests -v
```

**bot の実行（`uv run python src/main.py`）は行わないこと。** Discord トークンが必要であり、実際の Discord 動作確認は人間が行う。

## 変更時の注意

- 新しい feature を追加する場合は `cogs_loader.py` の `DEFAULT_EXTENSIONS` に登録する
- 新しい DB テーブルやカラムを追加する場合は `db.py` の `_SCHEMA_DDL` と `CURRENT_SCHEMA_VERSION` を更新する
- `test_architecture.py` を実行してモジュール境界が壊れていないことを確認する
