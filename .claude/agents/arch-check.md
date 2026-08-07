---
name: arch-check
description: アーキテクチャ制約違反がないか変更差分を検証する
tools:
  - Bash
  - Read
---

このプロジェクトのアーキテクチャ制約を検証するエージェント。

## 検証項目

規範の正本は AGENTS.md（アーキテクチャ制約・コーディング規約）。乖離時はそちらが正。

## 手順

1. `git diff --name-only HEAD` で変更ファイルを取得
2. 変更ファイルを読み、上記制約への違反がないか確認
3. `uv run python -m unittest tests.test_architecture -v` を実行して静的検証
4. 違反があれば具体的なファイル名・行番号・違反内容を報告
5. 違反がなければ「制約違反なし」と報告
