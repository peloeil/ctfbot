# AlpacaHack 連携 (alpacahack)

## 概要

AlpacaHack のユーザーを登録し、毎週日曜に solve 状況を集計・通知する。1 ファイル完結（スクレイパー + 週次ロジック + cog）。

## コマンド

`add` / `del` / `list` の応答は ephemeral、`solve` は public。`add` / `del` は `username.strip()` した値を `{name}` として扱う。空なら「ユーザー名が空です。」と応答し、`add` はさらに形式を検証する: 32 文字以内かつ `[0-9A-Za-z_-]` のみ。違反は「ユーザー名は 32 文字以内の英数字と `-` `_` で入力してください。」と応答する。成功時のみ `log_audit` を送信する。

### `/alpaca add username`

ユーザーを DB に登録する。登録数の上限は 50 人で、上限到達時は「登録数が上限（50人）に達しています。」と応答する。成功時「`{name}` を登録しました。」、既に登録済みなら「`{name}` は既に登録されています。」と応答。`log_audit(command_name="alpaca add", details=["ユーザー名: {name}"])`。

### `/alpaca del username`

ユーザーの登録を削除する。成功時「`{name}` の登録を削除しました。」、未登録なら「`{name}` は登録されていません。」と応答。`log_audit(command_name="alpaca del", details=["ユーザー名: {name}"])`。

### `/alpaca list`

登録済みユーザー一覧を名前順で表示。0 件なら「登録ユーザーはいません。」、それ以外は「登録ユーザー ({n}人):」+ `- {user}` 行。

`list` の応答は分割しない（username 32 文字・登録 50 人の上限により Discord の 2000 文字上限に収まる）。登録ユーザーは bot 全体で共有され、guild ごとに分離しない（1 bot = 1 コミュニティ運用の前提）。

### `/alpaca solve`

`interaction.response.defer()` → 今週の solve 状況を集計 → Embed で応答。guild ごとに 60 秒 1 回のクールダウンを設ける（超過時は共通エラーハンドラの「コマンドはクールダウン中です。」）。登録 0 人でも Embed を送る（`0人/0人, 0 solves`・field なし）。

## 週次通知

- 毎日 `ALPACAHACK_SOLVE_TIME` に起動し、日曜（`weekday() == 6`）のみ実行
- `ALPACAHACK_CHANNEL_ID` のチャンネルへ Embed を送信する。チャンネルが未設定・解決不能ならこの回は集計（スクレイピング）自体を行わずスキップする
- 実行時刻の設定は cog の `__init__` で `.start()` の前に `change_interval(time=...)` で行う（理由は docs/design.md「週次通知の実行時刻は start 前に設定する」）
- 集計全体の失敗はログのみでチャンネルへは通知しない（ユーザー単位の失敗は Embed の「取得失敗」に表示される。単一 API の失敗で週次通知が黙って消える ctftime とは異なる、意図的な非対称）
- 日曜 23:00 実行のため、同日の実行時刻以降の solve はその週の通知に含まれない（既知の制限。`/alpaca solve` では参照できる）

## スクレイパー (AlpacaHackClient)

```
GET https://alpacahack.com/users/{username}/solved-challenges[?solvesPage={page}]
```

- タイムアウト: `request_timeout`（デフォルト 10 秒）
- ページネーション: 1 ページ目はパラメータなし、2 ページ目以降は `solvesPage` パラメータ
- 1 ページ 10 件。取得件数が 10 未満でページネーション終了
- 最大 20 ページまで
- `since` が指定されている場合、ページ内の最後のレコードの solve 日付（`settings.tzinfo` の date）が `since` より前ならページネーション終了する。この早期終了はページが solve 日時の降順（新しい順）で並ぶことを前提とする
- ページ間に `page_interval`（デフォルト 0.2 秒）の待機
- HTTP エラーステータス（4xx/5xx）は `raise_for_status` で検出し `RequestException` として扱う（リトライしない）。redirect は requests の既定に従う
- `username` は `add` の形式検証（`[0-9A-Za-z_-]`）により、URL エンコードせずパスへ連結できる
- `RequestException` → `ExternalAPIError("AlpacaHack からの取得に失敗しました。")`

### HTML パース

「SOLVED CHALLENGES」セクションの `<table>` を探し、見出しが見つからなければページ内最初の `<table>` にフォールバックする。見出しもテーブルも無いページは 0 件として扱う。既知の制限: サイトの HTML 構造変更を solve 0 件と区別できない（フォールバックはマークアップ変動への耐性を優先する意図的な選択）。対象テーブルの各行を次の規則でパースする:
- 各 `<tr>` の `<td>[0]`: challenge name（`<a>` タグの text と href。href は `https://alpacahack.com` 基準で絶対 URL 化。`<a>` が無ければセルの text を使い URL は None）
- 各 `<tr>` の `<td>[2]`: solved_at（`aria-label` 属性を持つ子孫要素。なければセルのテキストをパース対象にする）
- solved_at のパース: `r"(\d{4}[-/]\d{2}[-/]\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)"` → UTC として解釈 → `settings.tzinfo` へ変換
- `<td>` が 3 個未満・challenge name が空・solved_at がパース不能な行はスキップする

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

`select_weekly_solves`: `solved_at` 昇順にソートした上で、`challenge_url or challenge_name` をキーに最初の出現（最も早い solve）を残して重複除去する。週の範囲判定は `week_start <= solved_at.date() <= week_end`（両端を含む。`settings.tzinfo` の日付で判定する）。

## Embed 形式

```
タイトル: 🦙 AlpacaHack 今週の solve
カラー: #FD8028（AlpacaHack ブランドカラー）

description:
{week_start} 〜 {week_end}   ← ISO 形式 (YYYY-MM-DD)
{solved_users}人/{total_users}人, {total_solves} solves
（solved_users = 今週 1 件以上 solve したユーザー数）
（取得失敗 {len(failed_users)}人 ← 0人なら省略）

各ユーザー（ユーザー名昇順 = `list_alpacahack_users` の取得順）→ Embed field:
name: {username} ({len(solves)} solves)
value:
- [{challenge_name}]({url})  ← url が None なら名前のみ
- ...
（12 件まで。超過時は "... 他 {n} 件"。0 件なら "-"）
（1024 文字超過時は value[:1021] + "..."）

表示するユーザーは MAX_EMBED_FIELDS - 1 (24) 人まで。
省略ユーザーまたは failed_users があれば最後に field を 1 つ追加:
name: 「その他 / 取得失敗」（failed_users なしなら「その他」）
value: 「他 {omitted} 人は省略しました。」「取得失敗: {name}, ...」の該当行
（value は 1024 文字で切り詰め）
```

Embed 全体の合計は 6000 文字以内に収める: field 追加で超過する場合はそこで打ち切り、以降のユーザーは省略人数として最終 field に合算する。field name（`{username} ({n} solves)`）は username の 32 文字制限により 256 文字上限に収まる。challenge 名または URL がリンク構文を壊す文字（`]`・`(`・`)`）を含む場合はリンク化せず名前のみ表示する（`docs/core.md` の escape 方針）。

## データモデル

`SolveRecord` / `WeeklySolveSummary` の定義は `docs/data-contracts.md`「alpacahack」を正本とする。`weekly_solves` は username → 今週の solve list で、取得に失敗したユーザーは含まれず `failed_users` にのみ入る。

## DB スキーマ

テーブル `alpacahack_user` の DDL は `docs/data-contracts.md` を正本とする。設計上のポイント: `name` は UNIQUE（`/alpaca add` の重複判定）。

## 関連設定

| 環境変数 | デフォルト | 説明 |
|---|---|---|
| `ALPACAHACK_CHANNEL_ID` | 0 | 通知先チャンネル（0 で無効） |
| `ALPACAHACK_SOLVE_TIME` | 23:00 | 通知時刻（日曜のみ実行） |
