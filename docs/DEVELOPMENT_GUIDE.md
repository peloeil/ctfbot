# Development Guide

このドキュメントは人間の開発者向けです。セットアップと運用前提は `README.md`、coding agent 向けの拘束条件は `AGENTS.md` を参照してください。

## 変更前に確認すること

- 変更対象の feature または cog と、その対応テストを先に読む
- ドキュメントと実装が食い違う場合は `src/` と `tests/` を優先する
- 変更は既存パターンに合わせて最小限に保つ

## アーキテクチャ

依存は上位から下位にだけ向けます。

- 基本:
  `cog -> usecase -> repository/integrations/application`
- `service` は feature 内で再利用する業務操作がある場合のみ、
  `usecase` と下位層の間に置く

各層の責務:

- `cog`
  Discord I/O、permission、interaction、scheduled task
- `usecase`
  業務フロー
- `service`
  feature の業務操作。必要な場合のみ `repository` `integrations` `application`
  を束ねる
- `integrations`
  外部 API、scraping、レスポンス parse などの外部依存
- `application`
  I/O を持たない日付判定、正規化、分割、重複除去などの pure logic
- `repository`
  DB 永続化
- `db`
  接続と current schema の初期化・検証

Runtime の組み立て:

- `src/bot/runtime_providers.py`
  依存を構築し、DB の current schema を初期化または検証する
- `src/bot/runtime.py`
  runtime にまとめて cog から参照できる形にする
- `src/bot/cogs_loader.py`
  本番でロードする extension を定義する

## 変更の進め方

### 新機能を追加する場合

1. `src/bot/features/<feature>/` を作る
2. 必要なら `models.py` と `repository.py` を追加する
3. 外部 API や scraping があれば `src/bot/integrations/` に切り出す
4. I/O を持たないロジックがあれば `src/bot/application/` に切り出す
5. feature 内で再利用する業務操作があれば `service.py` を追加する
6. `usecase.py` に業務フローを実装する
7. `cog.py` で Discord 公開面を実装する
8. `src/bot/runtime_providers.py` と `src/bot/runtime.py` に配線する
9. `src/bot/cogs_loader.py` に登録する
10. 対応するテストを追加する

### 既存機能を変更する場合

- Discord の入出力は `cog` に閉じ込める
- blocking I/O は `integrations` `repository` `service` に閉じ込める
- 外部依存の詳細は `integrations` に閉じ込める
- I/O を持たないロジックは `application` に寄せる
- 例外は `bot.errors` の型で表現する
- slash command を変更したら bot を再起動する

## テスト方針

- 純粋ロジックは `application` / `usecase` を `unittest` で検証する
- 外部依存の parse や API client は `integrations` を `unittest` で検証する
- DB 変更は一時 DB を使う repository / current schema テストで検証する
- Discord 側の分岐は `AsyncMock` を使う cog テストで検証する
- 依存境界は `tests/test_architecture.py` が検知する
- 仕様変更時は対応する `test_*.py` を先に確認し、必要なら更新する

## PR 前に見る項目

- 依存方向を壊していない
- 変更内容に対応するテストがある
- CI 相当のローカルチェックを通している
- 挙動変更があれば該当ドキュメントを更新している

ローカルで回す具体的なチェックコマンドは `.github/workflows/ci.yml` を参照してください。
