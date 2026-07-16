# GitHub CI

## 概要

PR と main ブランチへの push で lint・型チェック・テストを自動実行する。

## ワークフロー

ファイル: `.github/workflows/ci.yml`

### トリガー

| イベント | 対象 |
|---|---|
| `push` | `main` ブランチ |
| `pull_request` | `main` ブランチ向け |

### 実行環境

Python 3.14・`ubuntu-latest` のみ（`strategy.matrix` は使わない）。

### ジョブ

`lint`（Ruff の check + format --check）、`type-check`（ty）、`test`（unittest）の 3 ジョブ。いずれも checkout → `astral-sh/setup-uv` → `uv sync --group dev` → 各コマンドの構成。具体的な steps とコマンドは `ci.yml` を正とする（このドキュメントに写しを持たない）。

## 設計判断

### 3 ジョブに分離する理由

- lint は数秒で終わるため、型チェックやテストの完了を待たずにフィードバックを返せる
- 失敗原因が一目で分かる（lint 失敗 vs 型エラー vs テスト失敗）
- ジョブが並列実行されるため全体の所要時間は最も遅いジョブに律速される

### `astral-sh/setup-uv` を使う理由

- uv のインストールとキャッシュを 1 アクションで処理できる
- `uv python install` による Python 3.14 のセットアップも自動化される

### Python バージョンの指定方法

`.python-version` ファイル（内容: `3.14`）が既にリポジトリにある。`setup-uv` はデフォルトでこのファイルを読み、対応する Python を自動インストールする。ワークフロー側でバージョンを重複指定しない。

### キャッシュ

`astral-sh/setup-uv@v6` は uv のキャッシュディレクトリを自動的にキャッシュする（`enable-cache` のデフォルトが true）。追加のキャッシュ設定は不要。
