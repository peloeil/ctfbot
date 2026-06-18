# CTFtime 通知 (ctftime)

## 概要

CTFtime API から近日開催の CTF イベントを取得し、週次で通知する。`/ctftime` コマンドで手動取得も可能。

## コマンド

### `/ctftime`

`interaction.response.defer()` → イベント取得 → Embed で応答。
取得失敗時は「CTFtime からの取得に失敗しました。」と応答。

## 週次通知

- 毎日 `CTFTIME_NOTIFICATION_TIME` に起動し、月曜（`weekday() == 0`）のみ実行
- `CTFTIME_CHANNEL_ID` に Embed を送信（0 なら何もしない）

## API クライアント (CTFTimeClient)

```
GET https://ctftime.org/api/v1/events/?limit={limit}&start={start_unix}&finish={finish_unix}
Headers: User-Agent={ctftime_user_agent}
```

- `start` = 現在時刻、`finish` = 現在 + `CTFTIME_WINDOW_DAYS` 日
- リトライ: 最大 `max_retries`（デフォルト 3）回。間隔 = `retry_backoff * attempt` 秒
- 全失敗 → `ExternalAPIError`

### レスポンスパース

JSON 配列の各要素から:
- `title`: str
- `start` / `finish`: ISO 8601 文字列 → `datetime.fromisoformat` → タイムゾーン変換
- `ctftime_url`: str（なければ `url` フィールド）

"Z" 付き・オフセット付き両方の ISO datetime をサポート。

## Embed 形式

```
タイトル: 📅 今後{window_days}日間のCTFイベント

各イベント:
**{title}**
🕐 <t:{start_unix}:f> 〜 <t:{finish_unix}:f>
🔗 [CTFtime]({ctftime_url})
```

- 0 件: 「予定されているイベントはありません。」
- description 4096 文字上限で打ち切り

## データモデル

```python
@dataclass(frozen=True, slots=True)
class CTFEvent:
    title: str
    start: datetime.datetime
    finish: datetime.datetime
    ctftime_url: str
```

## 関連設定

| 環境変数 | デフォルト | 説明 |
|---|---|---|
| `CTFTIME_CHANNEL_ID` | 0 | 通知先チャンネル（0 で無効） |
| `CTFTIME_NOTIFICATION_TIME` | 09:00 | 通知時刻（月曜のみ実行） |
| `CTFTIME_WINDOW_DAYS` | 14 | 取得する期間（日数） |
| `CTFTIME_EVENT_LIMIT` | 20 | 取得するイベント数上限 |
| `CTFTIME_USER_AGENT` | `ctfbot/2.0 (+discord)` | API リクエストの User-Agent |
