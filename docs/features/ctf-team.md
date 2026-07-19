# CTF 募集管理 (ctf_team)

## 概要

`/ctfteam` コマンドグループで CTF 参加者の募集を管理する。募集の作成・一覧・終了・アーカイブのライフサイクルを持つ。コマンド応答はすべて ephemeral。

## ファイル構成

| ファイル | 責務 |
|---|---|
| `models.py` | `ActiveCampaign`, `ClosedCampaign`, `Campaign`（union alias）, `CampaignDraft`, `CampaignStatus` データモデル |
| `campaign.py` | 入力パース（`parse_campaign_draft`）・事前条件確認（`ensure_campaign_can_be_created`）・ビジネスロジック（Discord 非依存） |
| `discord_ops.py` | Discord リソース操作（チャンネル・ロール・メッセージ）、boundary 関数（`require_category`, `require_role_channel`） |
| `cog.py` | スラッシュコマンド定義・イベントリスナー・バックグラウンドタスク |

## ライフサイクル

```
active ──(end_at_unix 到達 or /ctfteam close)──→ closed ──(archive_at_unix 到達 or /ctfteam archive)──→ archived
```

DB の `status` は `'active'` / `'closed'` の 2 値のみ。archived は独立した status ではなく、closed 行の `archived_at_unix` が非 NULL であることで表現する。

### active 状態

- 募集メッセージが募集チャンネル（`CTF_TEAM_ROLE_CHANNEL_ID`）に投稿されている
- リアクション (✅) でロール付与が行われる
- discussion / voice チャンネルが存在する

### closed 状態

- 募集メッセージに `🔒 **この募集は終了しました。**` ヘッダーが追加される
- voice チャンネルは削除される
- discussion チャンネルに参加メンバースナップショットが投稿される
- `archive_at_unix` = `closed_at_unix` + `ARCHIVE_DELAY_DAYS` 日が設定される（定数表参照）

#### close 処理の順序（冪等性保証）

close は毎分ループからリトライされるため、以下の順序で行う:

1. 募集メッセージへのヘッダー追加（冪等: ヘッダー既存なら何もしない。メッセージが `NotFound`、または募集チャンネルが TextChannel として解決できない場合は成功扱い）
2. voice チャンネル削除（冪等: `NotFound` は成功扱い）
3. 1・2 のいずれかが失敗したら中断（DB は active のまま。翌分リトライ）
4. DB を closed に更新（`WHERE status='active'` 条件付き UPDATE による atomic claim）
5. **4 で実際に active → closed へ遷移した場合のみ**、スナップショットを送信。ただし discussion チャンネルとロールの両方が解決できた場合に限る（どちらかが消失していれば送信しないが close は成功）

スナップショット送信自体の失敗は close を巻き戻さない。

### archived 状態

- discussion チャンネルが archive カテゴリに移動される
- チャンネルは読み取り専用になる（全員閲覧可、送信不可）
- ロールが削除される

#### archive 処理の順序（冪等性保証）

close と同じく「Discord リソース → DB → 通知」の順で行う。archive カテゴリ（`settings.ctf_team_archive_category_id`）が解決できなければその時点で失敗（DB 未更新、リトライ対象）。それ以外のリソース操作は途中で失敗しても最後まで試行し、**すべて成功した場合のみ** DB を更新する:

1. discussion チャンネルの archive（`NotFound` は成功扱い）: bot へ `manage_channels` overwrite を付与 → archive カテゴリへ移動 → `@everyone` を読み取り専用の権限に置き換え → ロールの overwrite を削除
2. voice チャンネルが残っていれば削除（`NotFound` は成功扱い）
3. ロールを削除（既に存在しなければ成功扱い）
4. `mark_archived`（`archived_at_unix IS NULL` 条件付き UPDATE による atomic claim）で DB に記録
5. **4 で claim に成功した場合のみ**、discussion チャンネルが TextChannel として解決できていれば「📦 このチャンネルは archive カテゴリに移動されました。」を `send_safely` で投稿。送信失敗は archive を巻き戻さない（DB が正）

## コマンド

### `/ctfteam open ctf_name [role_color]`

`role_color` はプリセット 9 色の Choice（省略時 `#3b82f6`）: 🟥 Red `#ef4444`・🟧 Orange `#f97316`・🟨 Yellow `#eab308`・🟩 Green `#22c55e`・🟦 Blue `#3b82f6`・🟪 Purple `#a855f7`・🟫 Brown `#92400e`・⬜ White `#f3f4f6`・⬛ Gray `#6b7280`（Choice 名は絵文字付き色名、value が hex 文字列）。値が `#RRGGBB` としてパースできない場合は「ロール色は #RRGGBB 形式で指定してください。」と応答し Modal を開かない（Choice 定義により通常は到達しない防御的分岐）。

1. Modal（title「CTF募集作成」）が開く。TextInput は 2 つ（いずれも `max_length=16`）: 開始日時（label「開始日時 (YYYY-MM-DD HH:MM)」・placeholder「2026-01-15 21:00」・必須）、終了日時（label「終了日時 (空欄で常設)」・placeholder「2026-01-17 21:00」・任意）
2. 入力パース（`campaign.parse_campaign_draft`。日時は `settings.tzinfo` の naive 時刻として解釈する。DST を持つタイムゾーンで存在しない・二重に存在する時刻は ZoneInfo の既定（fold=0）で解決し、拒否しない）→ 作成可否確認（`campaign.ensure_campaign_can_be_created`）
3. ロール作成（名前 = CTF 名、指定色、mentionable）→ discussion チャンネル作成 → voice チャンネル作成 → 募集メッセージ送信（`allowed_mentions` はロールのみ許可）→ ✅ リアクション追加
4. DB に campaign レコード作成
5. 作成者にロール付与（既に保持していればスキップ — 手順 3 の ✅ リアクション追加以降に作成者自身のリアクションをハンドラが先に処理した場合等に成立する競合対策。作成者が member cache から解決できない場合は付与自体を行わない）
6. 開始時刻が既に過ぎていれば即座に開始通知（下記 claim 機構経由）

手順 4 の DB insert 成功をもって募集作成は成功とする。

**DB insert 成功前（手順 1〜4）の失敗**は作成済み Discord リソースをロールバック（`discord_ops.cleanup_resources`。DB は対象外）:
- `ServiceError` → メッセージをそのまま表示
- `ConflictError` → 「同名の募集が作成されたか、active 募集数の上限に達しました。」
- その他の例外 → exception ログ + 「募集の作成中にエラーが発生しました。」

**DB insert 成功後（手順 5〜6）の失敗**は募集を巻き戻さない（`cleanup_resources` は実行しない）:
- 手順 5 のロール付与失敗（`discord.Forbidden`・`discord.HTTPException`）→ warning ログを記録し、成功応答に「⚠️ 作成者へのロール付与に失敗しました。募集メッセージに ✅ リアクションすると参加できます。」を改行で追記
- 手順 6 の即時開始通知の失敗 → ログのみ（送信失敗は warning、claim の例外は traceback 付き exception）。claim 未達なら毎分ループの `start_due_campaigns` が回収する

成功時の応答は「**{ctf_name}** の募集を作成しました。」+ `log_audit(details=["CTF名: {ctf_name}"])`。

DB insert（`create_campaign`）は DB レベルでも作成者の active 募集数と同名 active を再チェックし、違反は `ConflictError` を raise する（契約の正本は `docs/data-contracts.md`）。手順 2 の事前確認とこの再チェックの二段構えで、同時実行の競合を防ぐ。

バリデーションルール（`ServiceError` のメッセージ）:
- CTF 名: 空白正規化。空なら「CTF名を入力してください。」、`MAX_CTF_NAME_LENGTH` 超なら「CTF名が長すぎます。60文字以内で入力してください。」
- 日時: `YYYY-MM-DD HH:MM` 形式。不正なら「開始/終了日時の形式が不正です。YYYY-MM-DD HH:MM 形式で入力してください。」
- 終了日時: 省略可（常設）。開始日時以前なら「終了日時は開始日時より後にしてください。常設CTFの場合は終了日時を空欄にしてください。」
- 作成者の active 募集数上限: 「同時に作成できる active 募集数の上限に達しています。(上限: 5)」
- 同名 active 重複（大文字小文字無視）: 「同名の active 募集が既に存在します。別名を使うか既存募集を close してください。」

### `/ctfteam list [status]`

status: `active`（デフォルト）, `closed`, `all`。Choice 表示名は「募集中」「終了」「すべて」。`closed`・`all` は archive 済みも含む（表示上は区別されない）。

Embed（title「CTF募集一覧 ({status ラベル})」）で応答。0 件なら description は「該当する募集はありません。」。それ以外は先頭行「{n}件を表示しています。」（n は DB から取得した件数。最大件数は `list_campaigns` の limit（`docs/data-contracts.md`））に続けて、campaign ごとの以下のブロックを空行区切りで列挙する（`created_at_unix` 降順）:

```
**{index}. {ctf_name}**
状態: 募集中 or 終了
開始: <t:{start}:f> (<t:{start}:R>)
終了: <t:{end}:f> (<t:{end}:R>)   ← None なら "常設"
募集: [メッセージへ移動]({メッセージ URL})
議論: <#{discussion_id}>   ← 無ければ "-"
VC: <#{voice_id}>   ← 無ければ "-"
ロール: <@&{role_id}>
作成者: <@{created_by}>
archive予定: <t:{archive_at}:f> (<t:{archive_at}:R>)   ← closed 行のみ
```

description の 4096 文字上限を超えるブロック以降は載せず、「他 {m} 件は省略しています。」（m は未表示件数。このとき実表示は n − m 件）を追加して打ち切る。省略行を含めて 4096 文字に収まるよう、省略行の分の余白を確保する。

### `/ctfteam close ctf_name`

権限: 作成者 または `manage_guild` 権限保持者。

- active に見つからない → 「active 募集 '{ctf_name}' が見つかりません。」
- 権限なし → 「この募集を終了する権限がありません。」
- リソース操作失敗 → 「Discord リソースの更新に失敗したため、募集を終了しませんでした。」（DB 未更新）
- 成功 → 「**{ctf_name}** を終了しました。archive 予定: <t:{archive_at}:f> (<t:{archive_at}:R>)」+ `log_audit(details=["CTF名: {ctf_name}"])`
- 自動 close と同時実行して DB claim に負けた場合（処理中に既に closed になっていた場合）も成功応答を返す（冪等・目的達成扱い。スナップショットは claim に勝った側だけが送る）

### `/ctfteam archive ctf_name`

権限: close と同じ。権限なしは「この募集を archive する権限がありません。」。

対象が見つからない場合のエラーメッセージ:
- active で存在 → 「'{ctf_name}' は募集中です。先に `/ctfteam close` で終了してください。」
- 既に archived → 「'{ctf_name}' は既に archive 済みです。」
- 不在 → 「募集 '{ctf_name}' が見つかりません。」

リソース操作失敗 → 「Discord リソースの archive に失敗したため、DB状態を更新しませんでした。」
成功 → 「**{ctf_name}** を archive しました。」+ `log_audit(details=["CTF名: {ctf_name}"])`
自動 archive と同時実行して DB claim に負けた場合も成功応答を返す（冪等・目的達成扱い。archive 通知は claim に勝った側だけが送る）。

## リアクションハンドラ

`on_raw_reaction_add` で ✅ リアクションを監視。

- bot 自身のリアクションは無視
- 対象メッセージが active campaign でなければ無視
- campaign が期限切れの場合は自動 close（audit ログ省略）し、以降の処理は行わない
- ロールが guild から削除済みなら何もしない
- メンバーが解決できない（退出済み・照会失敗）場合は何もしない
- メンバーが既にロールを保持していれば何もしない（付与も参加通知もスキップ）
- ロールを付与し、discussion チャンネルに参加通知を投稿（付与失敗は warning ログのみで中断。参加通知は discussion チャンネルがテキストチャンネルとして解決できた場合のみ）

## バックグラウンドタスク（1分間隔）

| タスク | 内容 |
|---|---|
| `start_due_campaigns` | `start_at_unix` が到達した **active** campaign の discussion に開始通知を投稿（close 済みには通知しない） |
| `close_expired_campaigns` | `end_at_unix` が到達した active campaign を自動 close |
| `archive_closed_campaigns` | `archive_at_unix` が到達した closed campaign を自動 archive |

各タスクの対象取得は期日（`start_at_unix` / `end_at_unix` / `archive_at_unix`）の古い順に、1 分あたり `list_due_*` の limit 件（`docs/data-contracts.md`）ずつ。処理しきれなかった分は翌分に最古から再試行される。

リソース操作の失敗は warning ログを記録して翌分リトライし続ける（打ち切りなし）。`Forbidden` 等の恒久的失敗は毎分記録されるこの warning ログで検知し、権限を修正して解消する。

開始通知は二重送信防止のため claim 機構を通す: `mark_started` が `start_notified_at_unix IS NULL` 条件付き UPDATE で atomic に claim し、claim に成功した呼び出しだけが通知を送信する。`/ctfteam open` 直後の即時通知と毎分ループの両方が同じ claim を通る。

## Discord リソース操作 (discord_ops.py)

### boundary 関数

- `require_category`: `settings.ctf_team_category_id` のカテゴリを解決。失敗時「CTF募集カテゴリが見つかりません。」
- `require_role_channel`: `settings.ctf_team_role_channel_id` のチャンネルをテキストチャンネルとして解決する。失敗時（不在・テキストチャンネル以外）は「募集チャンネルが見つかりません。」。CTF募集カテゴリ内にある必要はない

### チャンネル名の正規化

`normalize_channel_name`: times の正規化（`docs/features/times.md`）を適用し、結果が空なら `"ctf"` にフォールバックする。

discussion チャンネルは normalize 結果を、voice チャンネルは `{normalize結果}-voice` を base として命名する。

`pick_unique_channel_name`: すべての候補名を 100 文字に切り詰める（`-voice` を含めて 100 文字を超える場合は末尾が欠ける。Discord のチャンネル名上限 100 文字を超えない）。カテゴリ内の全チャンネル（テキスト・ボイスを問わず）と名前が重複する場合は `base-2`, `base-3` ... を試し、suffix 込みで 100 文字に収まるよう base 側を切り詰める。

### チャンネル権限

**discussion チャンネル:**
- `@everyone`: `view_channel=False`
- ロール: `view_channel=True`, `send_messages=True`, `read_message_history=True`
- 作成者: 同上
- bot: 同上 + `manage_channels=True`

**voice チャンネル:**
- `@everyone`: `view_channel=False`
- ロール: `view_channel=True`, `connect=True`, `speak=True`, `stream=True`
- 作成者 / bot: 同上

### archive 後の権限

- `@everyone`: `view_channel=True`, `send_messages=False`, `add_reactions=False`, `create_public_threads=False`, `create_private_threads=False`, `read_message_history=True`
- ロールの overwrite は削除

### 募集メッセージ形式

```
📣 **{ctf_name}** 参加者募集

🕐 開始: <t:{start}:f> (<t:{start}:R>)
🏁 終了: <t:{end}:f> (<t:{end}:R>)   ← None なら "常設"
💬 CTFチャンネル: #discussion
👥 ロール: @role

✅ リアクションを付けると @role ロールを付与します。
```

`#discussion`・`@role` は実メンション（`<#id>`・`<@&id>`）。`@role` の ping は `allowed_mentions` のロール許可により実際に飛ぶ。

### 通知メッセージ形式

- 開始通知（discussion）: 「🚀 **{ctf_name}** が開始しました!」+ 参加メンバーのメンション（下記チャンク分割）
- スナップショット（discussion）: 「🔒 **{ctf_name}** の募集が終了しました。」+「参加メンバー ({N}人):」+ メンションチャンク
- 参加通知（discussion）: 「🙋 {mention} が **{ctf_name}** に参加しました。」

参加メンバーはロール保持者（member cache。`Intents.members` 前提）で、列挙順は保証しない。0 人の場合はヘッダー行のみ送る（スナップショットは「参加メンバー (0人):」まで）。ヘッダー行は `AllowedMentions.none()`、メンションチャンクは users のみ許可で送る（許可範囲の正本は `docs/core.md` のメンション方針）。

### メンション分割

`MENTION_CHUNK_SIZE`（定数表）ごとに分割して複数メッセージで送信。Discord の 2000 文字制限にマージンを持たせている。

## データモデル

定義は `docs/data-contracts.md`「ctf_team」を正本とする。

## DB スキーマ

テーブル `ctf_team_campaign` の DDL・query 契約は `docs/data-contracts.md` を正本とする。

## 関連設定

環境変数の定義は `docs/data-contracts.md`「設定契約」を正本とする。

## 定数

| 定数 | 値 | 説明 |
|---|---|---|
| `MAX_ACTIVE_PER_USER` | 5 | 同一ユーザーの active 募集上限 |
| `MAX_CTF_NAME_LENGTH` | 60 | CTF 名の最大文字数 |
| `ARCHIVE_DELAY_DAYS` | 30 | close から archive までの日数 |
| `INPUT_DATETIME_FORMAT` | `%Y-%m-%d %H:%M` | 日時入力形式 |
| `REACTION_EMOJI` | ✅ | 参加リアクション |
| `MAX_CHANNEL_NAME_LENGTH` | 100 | チャンネル名の最大長（Discord の上限に一致） |
| `MENTION_CHUNK_SIZE` | 1700 | メンション分割の 1 メッセージ上限 |

## 対象外

- ✅ リアクション解除によるロール剥奪・脱退処理（リアクションを外してもロールは維持される。脱退はロールの手動削除で行う）
