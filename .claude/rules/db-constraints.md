---
paths:
  - "src/bot/db.py"
---
- discord を import しない
- 全テーブル・全 SQL が db.py に収まる
- 新テーブル追加時は _SCHEMA_DDL に DDL を追加し CURRENT_SCHEMA_VERSION をインクリメント
