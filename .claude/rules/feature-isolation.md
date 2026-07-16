---
paths:
  - "src/bot/features/**"
---
- feature 間の相互 import 禁止（features/ 直下のすべての feature が対象。互いを import しない）
- Discord 非依存ロジックを独立してテスト・再利用する必要がある場合は別モジュールに分ける。小規模 feature では同居してよい
- campaign.py / models.py は discord を import しない
- discord_ops.py は bot.db を import しない
- 複数ステップの検証は ServiceError を raise し cog で try/except ServiceError で統一。単純な入力チェックは cog 内で直接応答してよい
