---
paths:
  - "src/bot/features/**"
---
- feature 間の相互 import 禁止（alpacahack, ctftime, times, utility, ctf_team は互いを import しない）
- Discord オブジェクトを受け取る関数とプリミティブ型のみの関数は別モジュール
- campaign.py / models.py は discord を import しない
- discord_ops.py は bot.db を import しない
- バリデーションは ServiceError を raise し、cog で try/except ServiceError で統一
