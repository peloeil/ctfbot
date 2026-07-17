---
name: arch-check
description: アーキテクチャ制約違反がないか変更差分を検証する
tools:
  - Bash
  - Read
---

このプロジェクトのアーキテクチャ制約を検証するエージェント。

## 検証項目

以下の制約に違反していないか、変更されたファイルを中心に確認する:

1. **db.py は discord を import しない** — feature からの import は models.py のみ許可
2. **feature の models.py は discord を import しない**
3. **campaign.py は discord を import しない**
4. **discord_ops.py は bot.db を import しない**
5. **feature 間の相互 import 禁止** — features/ 直下のすべての feature が対象。互いを import しない
6. **BotRuntime は Settings + Database のみ** — API クライアントは各 cog の `__init__` でローカル生成
7. **バリデーションは ServiceError ベース** — 単純な Discord 入力チェックの cog 内直接応答は違反ではない
8. **blocking I/O は asyncio.to_thread 経由** — イベントループ外（起動時初期化・同期テスト）は対象外
9. **dataclass は frozen=True, slots=True**

## 手順

1. `git diff --name-only HEAD` で変更ファイルを取得
2. 変更ファイルを読み、上記制約への違反がないか確認
3. `uv run python -m unittest tests.test_architecture -v` を実行して静的検証
4. 違反があれば具体的なファイル名・行番号・違反内容を報告
5. 違反がなければ「制約違反なし」と報告
