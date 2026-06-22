# CLAUDE.md

このプロジェクトでは **Claude が設計し、Codex が実装する**。

## Claude の役割

- 新機能の設計・仕様策定
- アーキテクチャ判断
- コードレビュー・バグ調査
- 小規模な修正の直接実装（下記「実装の判断基準」参照）

## 実装の判断基準

| 規模 | 担当 | 例 |
|---|---|---|
| 1 ファイル以内の修正・バグ修正 | Claude が直接実装 | typo 修正、既存関数のロジック修正、テスト追加 |
| 複数ファイルにまたがる変更・新機能 | Claude が設計 → Codex が実装 | 新 cog 追加、DB スキーマ変更を伴う機能 |

判断に迷ったらユーザーに確認する。

## 設計の出力フォーマット

新機能の設計時は `/design-spec` スキルを使用する。

## 開発コマンド

```bash
# 依存インストール
uv sync --group dev

# lint
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# 型チェック
uv run ty check

# テスト
uv run python -m unittest discover -s tests -v

# 実行（Discord トークンが必要）
uv run python src/main.py
```

## コーディング規約

- コード・変数名は英語。Discord に送信するユーザー向けメッセージは日本語
- dataclass は `frozen=True, slots=True`
- コメントは原則書かない。WHY が自明でない場合のみ 1 行
- blocking I/O は `asyncio.to_thread` 経由
