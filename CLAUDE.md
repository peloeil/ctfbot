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

新機能や大きな変更を設計するとき、以下の手順を踏む。

### 1. docs/ に仕様を書く

新機能なら `docs/features/{feature-name}.md` を作成する。既存機能の変更なら該当ファイルを更新する。

仕様ドキュメントには以下を含める:
- **概要** — 何をするか 1〜2 文
- **コマンド** — スラッシュコマンドの名前・引数・挙動・エラーケース
- **データモデル** — dataclass 定義（必要な場合）
- **DB スキーマ** — テーブル定義（必要な場合）
- **Embed / メッセージ形式** — Discord に送信するメッセージの形式
- **関連設定** — 環境変数（必要な場合）

`docs/features/ctf-team.md` を詳細な参考例、`docs/features/times.md` を最小の参考例として使う。

### 2. AGENTS.md の参照テーブルを更新する

`## 仕様リファレンス` のテーブルに新しいドキュメントへのポインタを追加する。

### 3. Codex 向けのプロンプトを出力する

仕様ドキュメントを書いた後、ユーザーが Codex に渡せるプロンプトを会話内に出力する。形式:

```
docs/features/{feature-name}.md の仕様を実装してください。
AGENTS.md の制約・規約・検証手順に従うこと。
```

## docs/ の鮮度管理

- Claude が設計変更を行った場合、対応する docs/ を即座に更新する
- Codex の実装結果をレビューした結果、仕様と乖離があれば docs/ を更新する
- docs/ の内容と実装が矛盾している場合は、実装を正とする（docs/ を実装に合わせて更新する）

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
