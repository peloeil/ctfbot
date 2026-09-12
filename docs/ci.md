# GitHub CI

実行内容は [.github/workflows/ci.yml](../.github/workflows/ci.yml) を参照する。`main` への push と `main` 宛の pull request で lint・型チェック・テストを実行する。ローカルの検証コマンドは [AGENTS.md](../AGENTS.md#検証)。

3 ジョブに分けることで検査を並列実行し、失敗箇所を判別しやすくする。各ジョブで環境構築を繰り返すコストより、フィードバック速度を優先する。テストの詳細出力は失敗時に表示する。

`setup-uv` で uv・Python・キャッシュを用意する。Python の指定は [.python-version](../.python-version) に集約し、変更時は [pyproject.toml](../pyproject.toml) の `requires-python` と整合させる。

依存同期は `uv sync --frozen` で既存の lockfile を使用する。lockfile の更新は行わず、`pyproject.toml` との整合性検査もこのオプションでは保証しない。
