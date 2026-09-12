# AlpacaHack 連携 (alpacahack)

AlpacaHack のユーザーを登録して毎週日曜に solve 状況を集計し、Daily AlpacaHack の新着問題を通知する。

実装: [cog.py](../../src/ctfbot/features/alpacahack/cog.py)・[service.py](../../src/ctfbot/features/alpacahack/service.py)。検証: [test_alpacahack.py](../../tests/test_alpacahack.py)。設定と保存の保証は [データ・設定契約](../data-contracts.md) を参照する。

## コマンド

`add` / `del` / `list` の応答は ephemeral、`daily` / `solve` は public。応答の正確な文面は `cog.py` を参照する。

### `/alpaca add username`

前後の空白を除去し、空の名前は拒否する。名前は 32 文字以内の ASCII 英数字・ハイフン・アンダースコアに限定する。登録数の上限は 50 人で、同名登録・上限到達を区別して案内する。上限判定と挿入は Database API 内で atomic に行い、同時実行でも上限を超えない。新規登録に成功した場合だけ、ユーザー名をコマンド実行ログに記録する。

### `/alpaca del username`

前後の空白を除去し、空の名前は拒否する。登録を削除し、成功と未登録を区別して案内する。削除に成功した場合だけ、ユーザー名をコマンド実行ログに記録する。

### `/alpaca list`

登録人数とユーザー一覧を名前順で表示する。0 件なら登録がないことを案内する。名前の文字数と登録人数の上限により 2000 文字以内に収まるため、応答は分割しない。登録は bot 全体で共有する。

### `/alpaca solve`

defer 後に今週の solve を集計し、Embed で応答する。guild ごとに 60 秒 1 回のクールダウンを設ける。登録 0 人でも、人数・solve 数が 0、ユーザー field なしの Embed を送る。

### `/alpaca daily`

defer 後に公開中の Daily 問題を取得し、Embed で応答する。guild ごとに 60 秒 1 回のクールダウンを設ける。通知済み DB は変更せず、定期通知を抑止しない。問題が未公開の場合と取得失敗を区別して public で案内する。

## 週次通知

- 毎日 `ALPACAHACK_SOLVE_TIME` に起動し、日曜（`weekday() == 6`）のみ実行
- `ALPACAHACK_CHANNEL_ID` のチャンネルへ Embed を送信する。チャンネルが未設定・解決不能ならこの回は集計（スクレイピング）自体を行わずスキップする
- 集計全体の失敗はログのみでチャンネルへは通知せず、失敗メッセージの通知は非目標とする。ユーザー単位の失敗は Embed の「取得失敗」に表示する
- 日曜の実行時刻以降の solve はその週の通知に含まれない。通知後も `/alpaca solve` では参照できる

## Daily 問題通知

- 毎日 `ALPACAHACK_DAILY_TIME` に `https://alpacahack.com/daily` を確認する
- `ALPACAHACK_CHANNEL_ID` が未設定・解決不能なら取得せずスキップする
- 「Today's Challenge」が公開中なら問題ページからタイトル、作問者、カテゴリ、難易度、概要、添付ファイル URL、出題期間を取得する
- challenge URL を `alpacahack_daily_notification` に挿入できた場合だけ本文 `🦙 Daily AlpacaHack` と Embed を送る。`ALPACAHACK_MENTION_ID` が設定されていれば、同じ本文で guild 内の対象ユーザーまたはロールをメンションする。対象を解決できない場合も Daily 通知自体は送る。DB 更新は送信より先に確定し、同じ公開期間や bot 再起動で再送しない
- 公開中の問題がなければ何も送らない。取得・パース・送信の失敗はログに記録し、次回以降のループを継続する
- 添付ファイルはダウンロード・再アップロードせず、AlpacaHack が公開する S3 URL へのリンクとして表示する

### Daily HTML パース

1. `/daily` の「Today's Challenge」を含む要素内から `/daily/challenges/{slug}` のリンクを取得する
2. card の表示テキストから作問者、カテゴリ、難易度を取得する
3. 問題ページの最初の `<h1>` をタイトルとする
4. markdown 描画要素の親要素から概要をプレーンテキスト化する。`details` は summary を表示し、本文を Discord の spoiler (`||...||`) にする。取得不能なら `meta[name=description]` にフォールバックする
5. `https://alpacahack-prod.s3.ap-northeast-1.amazonaws.com/` で始まるリンクを添付ファイルとする
6. challenge ページの `releaseAt` を開始、`/daily` の `activeEndsAt` を終了として取得し、`settings.tzinfo` に変換する

### Daily Embed

- title: `🦙 {title}`、title URL: challenge URL、color: `#FD8028`
- description: 問題概要。3500 文字を超える場合は省略する。空なら「問題ページを確認してください。」
- field: 「出題期間」。開始・終了を Discord timestamp で表示し、終了の相対時刻を併記する
- field: 「カテゴリ / 難易度」「作問者」
- 添付がある場合は「添付ファイル」field にファイル名付きリンクを表示し、1024 文字を超える場合は省略する

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
- 登録時に検証したユーザー名を URL のパスに使う
- リクエスト失敗は `ExternalAPIError` として呼び出し側へ伝える

### HTML パース

solve 一覧から問題名・リンク・解答日時を取得する。問題名は必須、リンクがなければ URL は `None`。相対リンクは AlpacaHack のベース URL で絶対 URL に変換する。日時はハイフンまたはスラッシュ区切りの日付と時分（秒は任意）を読み、UTC として解釈して `settings.tzinfo` へ変換する。必要な列・問題名が欠ける行、日時を解釈できない行はスキップする。

「SOLVED CHALLENGES」の表を優先し、見つからなければ最初の表を使う。表がなければ 0 件とするため、サイトの構造変更と solve 0 件を区別できない。これはマークアップ変動への耐性を優先した制限。セレクタとパース構文は `service.py` を参照する。

## 週次集計

登録ユーザー全員の solve を取得して今週分を集計する。ユーザー単位の `ExternalAPIError` は `failed_users` に記録し、残りの取得を続ける。ユーザー間には `request_interval`（デフォルト 0.2 秒）の待機を置く。

### 週の定義

`settings.tzinfo` の日付で、月曜から日曜までの両端を含む期間とする。

### 重複除去

`select_weekly_solves`: `solved_at` 昇順にソートした上で、`challenge_url or challenge_name` をキーに最初の出現（最も早い solve）を残して重複除去する。対象期間は上記の週の定義に従う。

## 週次 Embed

対象期間、solve した人数 / 登録人数、solve 総数、取得失敗人数を表示する。ユーザーを名前順の field にし、各 field に solve 件数と問題へのリンクを載せる。URL がなければ問題名のみ、solve 0 件は `-` と表示する。

| 制限 | 超過時の表示 |
|---|---|
| 1 ユーザーの問題 12 件 | 残件数を表示 |
| 1 field の value 1024 文字 | 1021 文字 + `...` |
| ユーザー field 24 人 | 最後の field に省略人数と取得失敗ユーザー |
| Embed 全体 6000 文字 | field 追加を打ち切り、残りの人数を最後の field に合算 |

最後の field は省略・失敗がある場合に追加し、value を 1024 文字に収める。色・ラベル・文面は `service.py` の Embed 生成を参照する。問題名または URL がリンク構文を壊す場合は、[共通の表示方針](../core.md#メンションと表示) に従って名前のみ表示する。
