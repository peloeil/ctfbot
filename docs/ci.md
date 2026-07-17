# GitHub CI

## 概要

PR と main ブランチへの push で lint・型チェック・テストを自動実行する。この文書が `.github/workflows/ci.yml` の正本であり、この定義だけからワークフローを再作成できる。

## ワークフロー定義

```yaml
name: CI

on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen --group dev
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/

  type-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen --group dev
      - run: uv run ty check

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen --group dev
      - run: uv run python -m unittest discover -s tests -v
```

- Python バージョンはワークフローで指定しない。`setup-uv@v6` がリポジトリの `.python-version`（内容: `3.14`）を読んで自動インストールする。バージョン変更は `.python-version` と `pyproject.toml` の `requires-python` を更新する（ワークフローに重複指定を持ち込まない）
- 実行環境は `ubuntu-latest` のみ（`strategy.matrix` は使わない）
- `--frozen` で lockfile を固定する（`uv.lock` と `pyproject.toml` の不整合を CI 失敗として検出し、再現性を保証する）
- `permissions`・同時実行の cancel（`concurrency`）・`timeout-minutes` は非目標とし、設定しない

## 設計判断

### 3 ジョブに分離する理由

- ジョブは並列実行されるため、全体の所要時間は最も遅いジョブの時間で済み、lint のような数秒で終わる検査は先にフィードバックを返せる
- 失敗原因が一目で分かる（lint 失敗 vs 型エラー vs テスト失敗）
- 代償として checkout・環境構築・依存同期を 3 回行う。setup-uv のキャッシュにより増分コストは小さく、フィードバック速度を優先する

### `astral-sh/setup-uv` を使う理由

- uv のインストール・キャッシュ・`.python-version` に基づく Python のセットアップを 1 アクションで処理できる
- `setup-uv@v6` は uv のキャッシュディレクトリを自動的にキャッシュする（`enable-cache` のデフォルトが true）。追加のキャッシュ設定は不要
