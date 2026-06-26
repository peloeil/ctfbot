---
paths:
  - "src/bot/features/**"
---
- feature 間の相互 import 禁止（alpacahack, ctftime, times, utility, ctf_team は互いを import しない）
- Discord 非依存ロジックを独立してテスト・再利用する必要がある場合は別モジュールに分ける。小規模 feature では同居してよい
- campaign.py / models.py は discord を import しない
- discord_ops.py は bot.db を import しない
- バリデーションは ServiceError を raise し、cog で try/except ServiceError で統一
