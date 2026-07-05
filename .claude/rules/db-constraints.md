---
paths:
  - "src/bot/db.py"
---
- discord を import しない
- feature からの import は models.py のみ許可（models.py は discord 非依存であること）
- 全テーブル・全 SQL が db.py に収まる
- スキーマ変更時は 3 点セット: _SCHEMA_DDL を更新し、CURRENT_SCHEMA_VERSION をインクリメントし、_MIGRATIONS に旧 version → 新 version の移行 SQL を追加
- 移行 SQL は再実行に耐える形（IF NOT EXISTS 等）で書く
