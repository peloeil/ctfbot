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
- blocking I/O は `asyncio.to_thread` 経由

## 情報の書き分け原則（必須）

**コードには How、テストコードには What、コミットログには Why、コードコメントには Why not。**

- **コード (How)**: 処理の流れは命名と分割だけで追えるようにする。コメントで補わない
- **テスト (What)**: テスト名は振る舞い仕様を記述する（例: `test_retry_after_close_does_not_resend_snapshot`）。assert は型ではなく期待値そのものを検証する
- **コミットログ (Why)**: subject は変更内容の要約、本文に「何が問題で、なぜこの変更か」を書く。fix / refactor / revert / 削除系コミットでは本文 1〜3 行を必須とする
- **コメント (Why not)**: 原則書かない。素直な書き方をあえて避けた箇所（一見バグに見える処理、マジックナンバーの根拠、意味のある実行順序など）のみ、理由を 1 行で書く
