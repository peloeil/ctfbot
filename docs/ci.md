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

### マトリクス

Python 3.14 のみ。OS は `ubuntu-latest` のみ。

### ジョブ: `lint`

Ruff による lint とフォーマットチェック。テストや型チェックと独立して高速に失敗できるよう分離する。

```
steps:
  - uses: actions/checkout@v4
  - uses: astral-sh/setup-uv@v6
  - run: uv sync --group dev
  - run: uv run ruff check src/ tests/
  - run: uv run ruff format --check src/ tests/
```

### ジョブ: `type-check`

ty による型チェック。

```
steps:
  - uses: actions/checkout@v4
  - uses: astral-sh/setup-uv@v6
  - run: uv sync --group dev
  - run: uv run ty check
```

### ジョブ: `test`

unittest によるテスト実行。

```
steps:
  - uses: actions/checkout@v4
  - uses: astral-sh/setup-uv@v6
  - run: uv sync --group dev
  - run: uv run python -m unittest discover -s tests -v
```

## 設計判断

### 3 ジョブに分離する理由

- lint は数秒で終わるため、型チェックやテストの完了を待たずにフィードバックを返せる
- 失敗原因が一目で分かる（lint 失敗 vs 型エラー vs テスト失敗）
- ジョブが並列実行されるため全体の所要時間は最も遅いジョブに律速される

### `astral-sh/setup-uv` を使う理由

- uv のインストールとキャッシュを 1 アクションで処理できる
- `uv python install` による Python 3.14 のセットアップも自動化される（`actions/setup-python` は 3.14 未対応の可能性がある）

### Python バージョンの指定方法

`.python-version` ファイル（内容: `3.14`）が既にリポジトリにある。`setup-uv` はデフォルトでこのファイルを読み、対応する Python を自動インストールする。ワークフロー側でバージョンを重複指定しない。

### キャッシュ

`astral-sh/setup-uv@v6` は uv のキャッシュディレクトリを自動的にキャッシュする（`enable-cache` のデフォルトが true）。追加のキャッシュ設定は不要。
