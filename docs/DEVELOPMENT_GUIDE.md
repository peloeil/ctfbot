# Development Guide

このドキュメントは、`ctfbot` 開発に新しく参加する人向けの実践ガイドです。

## 1. 最初の 5 分

1. 依存インストール

```bash
uv sync --group dev
```

2. 環境変数を準備

```bash
cp .env.example .env
```

3. テストと静的チェックを実行

```bash
uv run ruff check src tests
uv run ty check
uv run python -m unittest discover -s tests -v
```

4. bot 起動

```bash
uv run python src/main.py
```

## 2. 設計の見取り図

依存方向は常に次の向きです。

`feature cog -> usecase -> service/repository -> db`

- `cog`: Discord I/O のみ担当
- `usecase`: 機能の業務フロー
- `service`: 外部 API や解析処理
- `repository`: DB 永続化
- `db`: 接続と migration

境界違反は `tests/test_architecture.py` で検知します。

## 3. 機能追加の標準フロー

1. `src/bot/features/<feature>/` を作る
2. `service.py` で外部依存を閉じる
3. `usecase.py` で処理を組み立てる
4. `cog.py` で Discord コマンドを公開する
5. 必要なら `repository.py` を追加する
6. 層をまたいで共有する型がある場合は `models.py` を追加する
7. `src/bot/cogs_loader.py` の `DEFAULT_EXTENSIONS` に登録する
8. `tests/` にユニットテストを追加する

## 4. 例: 新しい機能の最小構成

`sample_notice` という機能を追加する場合の最小形です。

### `src/bot/features/sample_notice/service.py`

```python
class SampleNoticeService:
    def build_message(self, topic: str) -> str:
        return f"notice: {topic}"
```

### `src/bot/features/sample_notice/usecase.py`

```python
from .service import SampleNoticeService


class SampleNoticeUseCase:
    def __init__(self, service: SampleNoticeService) -> None:
        self._service = service

    def create_notice(self, topic: str) -> str:
        return self._service.build_message(topic)
```

### `src/bot/features/sample_notice/cog.py`

```python
from discord.ext import commands
from ...cogs._runtime import get_runtime


class SampleNotice(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = get_runtime(bot)
        self.usecase = self.runtime.sample_notice_usecase

    @commands.command(name="notice")
    async def notice(self, ctx: commands.Context, topic: str) -> None:
        await ctx.send(self.usecase.create_notice(topic))
```

## 5. テスト追加の基本

- 純粋ロジック: `service/usecase` を通常の `unittest` で検証
- Discord 側分岐: `tests/test_cogs.py` と同様に `AsyncMock` で検証
- 境界ルール: `tests/test_architecture.py` が落ちないことを確認

## 6. 例外の扱い

例外型は `bot.errors` を使います。

- `ConfigurationError`: 設定不備
- `RepositoryError`: DB 操作失敗
- `ServiceError`: サービス層失敗
- `ExternalAPIError`: 外部 API 障害

`cog` では例外をユーザー向けメッセージへ変換し、詳細はログに出します。

## 7. PR 前チェックリスト

1. `ruff` / `ty` / `unittest` がすべて通る
2. 依存方向が設計ルールを満たす
3. 変更機能に対応するテストがある
4. README またはこのガイドに必要な更新を反映した
