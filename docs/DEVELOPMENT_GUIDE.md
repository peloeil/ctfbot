# Development Guide

このドキュメントは人間の開発者向けです。セットアップと運用前提は `README.md`、coding agent 向けの拘束条件は `AGENTS.md` を参照してください。

## 変更前に確認すること

- 変更対象の feature または cog と、その対応テストを先に読む
- ドキュメントと実装が食い違う場合は `src/` と `tests/` を優先する
- 変更は既存パターンに合わせて最小限に保つ

## アーキテクチャ

依存方向は常に次の向きです。

`cog -> usecase -> service/repository -> db`

各層の責務:

- `cog`
  Discord I/O、permission、interaction、scheduled task
- `usecase`
  業務フロー
- `service`
  外部 API、HTML 解析、時刻変換などの外部依存
- `repository`
  DB 永続化
- `db`
  接続と migration

Runtime の組み立て:

- `src/bot/runtime_providers.py`
  依存を構築し、DB migration を適用する
- `src/bot/runtime.py`
  runtime にまとめて cog から参照できる形にする
- `src/bot/cogs_loader.py`
  本番でロードする extension を定義する

## 変更の進め方

### 新機能を追加する場合

1. `src/bot/features/<feature>/` を作る
2. `service.py` と `usecase.py` を先に作る
3. 必要なら `repository.py` と `models.py` を追加する
4. `cog.py` で Discord 公開面を実装する
5. `src/bot/runtime_providers.py` と `src/bot/runtime.py` に配線する
6. `src/bot/cogs_loader.py` に登録する
7. 対応するテストを追加する

### 既存機能を変更する場合

- Discord の入出力は `cog` に閉じ込める
- blocking I/O は `service` または `repository` に閉じ込める
- 例外は `bot.errors` の型で表現する
- slash command を変更したら開発用サーバーで reload と sync を行う

## テスト方針

- 純粋ロジックは `service` / `usecase` を `unittest` で検証する
- DB 変更は一時 DB を使う repository / migration テストで検証する
- Discord 側の分岐は `AsyncMock` を使う cog テストで検証する
- 依存境界は `tests/test_architecture.py` が検知する
- 仕様変更時は対応する `test_*.py` を先に確認し、必要なら更新する

## PR 前に見る項目

- 依存方向を壊していない
- 変更内容に対応するテストがある
- CI 相当のローカルチェックを通している
- 挙動変更があれば該当ドキュメントを更新している

ローカルで回す具体的なチェックコマンドは `.github/workflows/ci.yml` を参照してください。
