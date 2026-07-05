# AlpacaHack 連携 (alpacahack)

## 概要

AlpacaHack のユーザーを登録し、毎週日曜に solve 状況を集計・通知する。1 ファイル完結（スクレイパー + 週次ロジック + cog）。

## コマンド

### `/alpaca add username`

ユーザーを DB に登録する。既に登録済みなら「`{name}` は既に登録されています。」と応答。

### `/alpaca del username`

ユーザーの登録を削除する。未登録なら「`{name}` は登録されていません。」と応答。

### `/alpaca list`

登録済みユーザー一覧を名前順で表示。

### `/alpaca solve`

`interaction.response.defer()` → 今週の solve 状況を集計 → Embed で応答。

## 週次通知

- 毎日 `ALPACAHACK_SOLVE_TIME` に起動し、日曜（`weekday() == 6`）のみ実行
- `ALPACAHACK_CHANNEL_ID` に Embed を送信（0 なら何もしない）
- 実行時刻の設定は cog の `__init__` で `.start()` の前に `change_interval(time=...)` で行う（`before_loop` で設定すると bot 再起動時に即時実行が 1 回走り、二重送信になる。docs/design.md「週次通知の実行時刻は start 前に設定する」参照）

## スクレイパー (AlpacaHackClient)

```
GET https://alpacahack.com/users/{username}/solved-challenges[?solvesPage={page}]
```

- ページネーション: 1 ページ目はパラメータなし、2 ページ目以降は `solvesPage` パラメータ
- 1 ページ 10 件。取得件数が 10 未満でページネーション終了
- 最大 20 ページまで
- `since` が指定されている場合、最後のレコードの日付が `since` より前ならページネーション終了
- ページ間に `page_interval`（デフォルト 0.2 秒）の待機
- `RequestException` → `ExternalAPIError`

### HTML パース

「SOLVED CHALLENGES」セクションの `<table>` を探す:
- 各 `<tr>` の `<td>[0]`: challenge name（`<a>` タグの text と href）
- 各 `<tr>` の `<td>[2]`: solved_at（`aria-label` 属性）
- `aria-label` のパース: `r"(\d{4}[-/]\d{2}[-/]\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)"` → UTC として解釈 → タイムゾーン変換

## 週次集計 (collect_weekly_summary)

同期関数。cog からは `asyncio.to_thread` で呼ぶ。

1. `db.list_alpacahack_users()` で全ユーザー取得
2. 各ユーザーについて `client.fetch_solve_records(username, since=week_start)` を実行
3. `select_weekly_solves` で今週分をフィルタ
4. `ExternalAPIError` → `failed_users` に追加して続行
5. ユーザー間に `request_interval`（デフォルト 0.2 秒）の待機

### 週の定義

月曜始まり。`get_week_range(reference_date)`:
- `week_start = reference_date - timedelta(days=reference_date.weekday())`
- `week_end = week_start + timedelta(days=6)`

### 重複除去

`select_weekly_solves`: `challenge_url or challenge_name` をキーとして重複除去。`solved_at` 昇順でソート。

## Embed 形式

```
タイトル: 🦙 AlpacaHack 今週の solve
カラー: #FD8028（AlpacaHack ブランドカラー）

description:
{week_start} 〜 {week_end}
{solved_count}人/{total_users}人, {total_solves} solves
（取得失敗 {len(failed_users)}人 ← 0人なら省略）

各ユーザー → Embed field:
name: {username} ({len(solves)} solves)
value:
- [{challenge_name}]({url})  ← url が None なら名前のみ
- ...
（12 件まで。超過時は "... 他 {n} 件"）
（field の value は 1024 文字上限）

ユーザーが MAX_EMBED_FIELDS - 1 (24) 人を超えた場合は省略。
failed_users が非空なら最後の field に取得失敗ユーザー一覧。
```

## データモデル

```python
@dataclass(frozen=True, slots=True)
class SolveRecord:
    challenge_name: str
    challenge_url: str | None
    solved_at: datetime.datetime

@dataclass(frozen=True, slots=True)
class WeeklySolveSummary:
    week_start: datetime.date
    week_end: datetime.date
    total_users: int
    weekly_solves: dict[str, list[SolveRecord]]  # username → records
    failed_users: list[str]
```

## DB スキーマ

```sql
CREATE TABLE IF NOT EXISTS alpacahack_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
```

## 関連設定

| 環境変数 | デフォルト | 説明 |
|---|---|---|
| `ALPACAHACK_CHANNEL_ID` | 0 | 通知先チャンネル（0 で無効） |
| `ALPACAHACK_SOLVE_TIME` | 23:00 | 通知時刻（日曜のみ実行） |
