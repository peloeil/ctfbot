# Copilot Instructions for ctfbot

このファイルは `ctfbot` リポジトリにおける Copilot のプロジェクト固有ルールです。
特に **PR レビュー品質の向上** を主目的とします。

## 1. 基本方針

- Python 3.14 / `uv` ベースの Discord bot プロジェクトとして扱う
- CTF サーバー運用を前提に、fail-fast な設定検証と非同期運用の安全性を優先する
- 提案は「既存パターン準拠」「最小変更」「回帰リスク最小化」を優先する

## 2. レビュー時の優先順位

PR レビューでは、以下をこの順で優先して指摘する。

1. 仕様破壊・挙動回帰の可能性
2. 例外処理漏れ・エラーハンドリング劣化
3. 権限・セキュリティ・データ破損リスク
4. 設計境界違反（依存方向違反）
5. テスト不足
6. 可読性や軽微な改善（重大指摘がない場合のみ）

スタイルだけの指摘は、バグ/回帰リスクより後に扱う。

## 3. 設計ルール（必須）

- 依存方向: `cog -> usecase -> service/repository -> db`
- `src/bot/cogs/` から `src/bot/db/` を直接 import しない
- 新機能は `src/bot/features/<feature>/` 配下で実装する
- 例外は `bot.errors` の型を使い、層ごとに責務を分離する
- `tests/test_architecture.py` の境界ルールを壊す提案をしない

## 4. PR レビュー出力フォーマット

レビューコメントは次の形式を基本とする。

1. 重大度 (`High` / `Medium` / `Low`)
2. 問題の要約（1文）
3. 対象ファイルと行（可能なら明示）
4. 何が問題か（現在の挙動ベース）
5. どう直すべきか（具体案）
6. 必要なテスト（回帰防止観点）

重大な指摘がない場合は、明確に「重大な指摘なし」と書く。

## 5. レビュー観点チェックリスト

- 依存方向違反がないか
- `bot.errors` に沿った例外設計か
- Discord 権限（Manage Roles/Channels/Messages 等）を壊していないか
- 非同期処理で `await` 漏れ、タスク管理漏れ、例外握りつぶしがないか
- DB 変更時に migration / repository 影響が考慮されているか
- 新規/変更ロジックに対応するテストが追加されているか

## 6. 実装提案時の期待

- 変更理由と影響範囲を短く明示する
- 必要なテスト追加を同時に提案する
- 外部 API 連携や永続化は `service` / `repository` 層に閉じ込める
- 不要な大規模リファクタは避ける
- 型ヒントと既存ログスタイルを維持する

## 7. 品質チェックコマンド

提案や実装では、以下が通る状態を前提にする。

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check
uv run python -m unittest discover -s tests -v
```
