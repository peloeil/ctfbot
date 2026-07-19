# CTFtime 通知 (ctftime)

## 概要

CTFtime API から近日開催の CTF イベントを取得し、週次で通知する。`/ctftime` コマンドで手動取得も可能。

## コマンド

### `/ctftime`

`interaction.response.defer()` → イベント取得 → Embed で応答。
取得失敗時は「CTFtime からの取得に失敗しました。」と応答。defer を含めいずれも public。

## 週次通知

- 毎日 `CTFTIME_NOTIFICATION_TIME` に起動し、月曜（`weekday() == 0`）のみ実行
- `CTFTIME_CHANNEL_ID` のチャンネルへ Embed を送信する。チャンネルが未設定・解決不能ならこの回は API 取得自体を行わずスキップする
- 取得失敗（`ExternalAPIError`）時は例外をログに記録し、通知チャンネルに「CTFtime からの取得に失敗しました。」を送信する
- 実行時刻の設定順序は `docs/design.md`「週次通知の実行時刻は start 前に設定する」に従う

## API クライアント (CTFTimeClient)

```
GET https://ctftime.org/api/v1/events/?limit={limit}&start={start_unix}&finish={finish_unix}
Headers: User-Agent={ctftime_user_agent}
```

- `start` = 現在時刻、`finish` = 現在 + `CTFTIME_WINDOW_DAYS` 日
- タイムアウト: `request_timeout`（デフォルト 10 秒）
- リトライ: 合計 `max_retries`（デフォルト 3）回まで試行する（初回を含む）。失敗した試行の後、次の試行まで `retry_backoff * attempt` 秒待機する（`attempt` は 1 起点の試行番号。デフォルトでは 1.5 秒 → 3.0 秒）。対象は `requests.RequestException`（`raise_for_status` による 4xx/5xx を含み、区別せずリトライ）・`ValueError`（JSON パース失敗）・`ExternalAPIError`（不正レスポンス）。`Retry-After` ヘッダーは参照しない（非目標）
- 全失敗 → `ExternalAPIError`

### レスポンスパース

JSON 配列の各要素から:
- `title`: str（なければ `"Untitled"`）
- `start` / `finish`: ISO 8601 文字列 → `datetime.fromisoformat` → `settings.tzinfo` へ変換
- `ctftime_url`: str（なければ `url` フィールド。両方なければ `""`）

"Z" 付き・オフセット付き両方の ISO datetime をサポート。tzinfo なしは UTC とみなす。

異常系（いずれもリトライ対象）:
- payload が配列でない → `ExternalAPIError("Unexpected CTFtime response.")`
- 要素が dict でない、または `start` / `finish` が欠落 → `ExternalAPIError("Unexpected CTFtime event.")`

1 件でも不正な要素があればレスポンス全体を不正としてリトライする（部分的な採用はしない）。`title` は欠落時 `"Untitled"`、文字列以外の型も文字列化して受理する。`start > finish` は検証しない（そのまま表示する）。

## Embed 形式

```
タイトル: 📅 今後{window_days}日間のCTFイベント

各イベント:
**{title}**
🕐 <t:{start_unix}:f> 〜 <t:{finish_unix}:f>
🔗 [CTFtime]({ctftime_url})
```

- イベントは API の返却順のまま表示する（並べ替えない）
- `ctftime_url` が空、またはリンク構文を壊す文字を含む場合は 🔗 行を出力しない（対象文字の正本は `docs/core.md` の escape 方針）
- 0 件: 「予定されているイベントはありません。」
- description はイベントブロック単位で構築し、4096 文字を超えるブロック以降は載せない（省略通知は出さない）

## データモデル

`CTFEvent` の定義は `docs/data-contracts.md`「ctftime」を正本とする。

## 関連設定

環境変数の定義は `docs/data-contracts.md`「設定契約」を正本とする。
