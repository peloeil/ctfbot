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

- 募集メッセージが `#role` チャンネルに投稿されている
- リアクション (✅) でロール付与が行われる
- discussion / voice チャンネルが存在する

### closed 状態

- 募集メッセージに `🔒 **この募集は終了しました。**` ヘッダーが追加される
- voice チャンネルは削除される
- discussion チャンネルに参加メンバースナップショットが投稿される
- `archive_at_unix = closed_at_unix + 30日` が設定される

#### close 処理の順序（冪等性保証）

close は毎分ループからリトライされるため、以下の順序で行う:

1. 募集メッセージへのヘッダー追加（冪等: ヘッダー既存なら何もしない。メッセージが `NotFound`、または募集チャンネルが TextChannel として解決できない場合は成功扱い）
2. voice チャンネル削除（冪等: `NotFound` は成功扱い）
3. 1・2 のいずれかが失敗したら中断（DB は active のまま。翌分リトライ）
4. DB を closed に更新
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
3. ロールを削除
4. `mark_archived`（`archived_at_unix IS NULL` 条件付き UPDATE による atomic claim）で DB に記録
5. **4 で claim に成功した場合のみ**、discussion チャンネルが TextChannel として解決できていれば「📦 このチャンネルは archive カテゴリに移動されました。」を `send_safely` で投稿。送信失敗は archive を巻き戻さない（DB が正）

## コマンド

### `/ctfteam open ctf_name [role_color]`

`role_color` はプリセット 9 色（Red 〜 Gray）の Choice（省略時 `#3b82f6`）。値が `#RRGGBB` としてパースできない場合は「ロール色は #RRGGBB 形式で指定してください。」と応答し Modal を開かない（Choice 定義により通常は到達しない防御的分岐）。

1. Modal が開く（開始日時・終了日時を入力。TextInput は `max_length=16`）
2. 入力パース（`campaign.parse_campaign_draft`。日時は `settings.tzinfo` で解釈）→ 作成可否確認（`campaign.ensure_campaign_can_be_created`）
3. ロール作成 → discussion チャンネル作成 → voice チャンネル作成 → 募集メッセージ送信（`allowed_mentions` はロールのみ許可）→ ✅ リアクション追加
4. DB に campaign レコード作成
5. 作成者にロール付与（既に保持していればスキップ）
6. 開始時刻が既に過ぎていれば即座に開始通知（下記 claim 機構経由）

手順 4 の DB insert 成功をもって募集作成は成功とする。

**DB insert 成功前（手順 1〜4）の失敗**は作成済み Discord リソースをロールバック（`discord_ops.cleanup_resources`。DB は対象外）:
- `ServiceError` → メッセージをそのまま表示
- `ConflictError` → 「同名の募集が作成されたか、active 募集数の上限に達しました。」
- その他の例外 → 「募集の作成中にエラーが発生しました。」

**DB insert 成功後（手順 5〜6）の失敗**は募集を巻き戻さない（`cleanup_resources` は実行しない）:
- 手順 5 のロール付与失敗（`discord.Forbidden`・`discord.HTTPException`）→ warning ログを記録し、成功応答に「⚠️ 作成者へのロール付与に失敗しました。募集メッセージに ✅ リアクションすると参加できます。」を改行で追記
- 手順 6 の即時開始通知の失敗 → ログのみ（送信失敗は warning、claim の例外は traceback 付き exception）。claim 未達なら毎分ループの `start_due_campaigns` が回収する

成功時の応答は「**{ctf_name}** の募集を作成しました。」+ `log_audit(details=["CTF名: {ctf_name}"])`。

DB insert（`create_campaign`）は `BEGIN IMMEDIATE` トランザクション内で作成者の active 募集数を再カウントし、超過または同名 active の unique index 違反で `ConflictError` を raise する。手順 2 の事前確認とこの DB レベル再チェックの二段構えで、同時実行の競合を防ぐ。

バリデーションルール（`ServiceError` のメッセージ）:
- CTF 名: 空白正規化。空なら「CTF名を入力してください。」、60 文字超なら「CTF名が長すぎます。60文字以内で入力してください。」
- 日時: `YYYY-MM-DD HH:MM` 形式。不正なら「開始/終了日時の形式が不正です。YYYY-MM-DD HH:MM 形式で入力してください。」
- 終了日時: 省略可（常設）。開始日時以前なら「終了日時は開始日時より後にしてください。常設CTFの場合は終了日時を空欄にしてください。」
- 作成者の active 募集数上限: 「同時に作成できる active 募集数の上限に達しています。(上限: 5)」
- 同名 active 重複（大文字小文字無視）: 「同名の active 募集が既に存在します。別名を使うか既存募集を close してください。」

### `/ctfteam list [status]`

status: `active`（デフォルト）, `closed`, `all`

Embed 形式で最大 20 件表示（`list_campaigns` の limit）。各 campaign について状態・開始/終了日時・募集メッセージリンク・discussion/VC チャンネル・ロール・作成者を表示。closed の行には archive 予定時刻を追加表示。description 4096 文字上限で打ち切り。

### `/ctfteam close ctf_name`

権限: 作成者 または `manage_guild` 権限保持者。

- active に見つからない → 「active 募集 '{ctf_name}' が見つかりません。」
- 権限なし → 「この募集を終了する権限がありません。」
- リソース操作失敗 → 「Discord リソースの更新に失敗したため、募集を終了しませんでした。」（DB 未更新）
- 成功 → 「**{ctf_name}** を終了しました。archive 予定: {timestamp}」+ `log_audit(details=["CTF名: {ctf_name}"])`

### `/ctfteam archive ctf_name`

権限: close と同じ。権限なしは「この募集を archive する権限がありません。」。

対象が見つからない場合のエラーメッセージ:
- active で存在 → 「'{ctf_name}' は募集中です。先に `/ctfteam close` で終了してください。」
- 既に archived → 「'{ctf_name}' は既に archive 済みです。」
- 不在 → 「募集 '{ctf_name}' が見つかりません。」

リソース操作失敗 → 「Discord リソースの archive に失敗したため、DB状態を更新しませんでした。」
成功 → 「**{ctf_name}** を archive しました。」+ `log_audit(details=["CTF名: {ctf_name}"])`

## リアクションハンドラ

`on_raw_reaction_add` で ✅ リアクションを監視。

- bot 自身のリアクションは無視
- 対象メッセージが active campaign でなければ無視
- campaign が期限切れの場合は自動 close（audit ログ省略）
- メンバーが既にロールを保持していれば何もしない（付与も参加通知もスキップ）
- ロールを付与し、discussion チャンネルに参加通知を投稿

## バックグラウンドタスク（1分間隔）

| タスク | 内容 |
|---|---|
| `start_due_campaigns` | `start_at_unix` が到達した campaign の discussion に開始通知を投稿 |
| `close_expired_campaigns` | `end_at_unix` が到達した active campaign を自動 close |
| `archive_closed_campaigns` | `archive_at_unix` が到達した closed campaign を自動 archive |

各タスクの対象取得は 20 件/分ずつ。

開始通知は二重送信防止のため claim 機構を通す: `mark_started` が `start_notified_at_unix IS NULL` 条件付き UPDATE で atomic に claim し、claim に成功した呼び出しだけが通知を送信する。`/ctfteam open` 直後の即時通知と毎分ループの両方が同じ claim を通る。

## Discord リソース操作 (discord_ops.py)

### boundary 関数

- `require_category`: `settings.ctf_team_category_id` のカテゴリを解決。失敗時「CTF募集カテゴリが見つかりません。」
- `require_role_channel`: 名前が `role` のテキストチャンネルを解決。失敗時「#role チャンネルが見つかりません。」

### チャンネル名の正規化

`normalize_channel_name`: lowercase → スペースを `-` に → `[^a-z0-9\-]` を `-` に置換 → 連続 `-` を 1 つに → 先頭末尾 `-` 除去 → 結果が空なら `"ctf"` にフォールバック → 100 文字で切る（times の正規化と似ているが、フォールバックの有無が異なる）。

discussion チャンネルは normalize 結果を、voice チャンネルは `{normalize結果}-voice` を base として命名する。

`pick_unique_channel_name`: カテゴリ内で重複する場合 `base-2`, `base-3` ... を試す。suffix 付与時は全体が 100 文字に収まるよう base 側を切り詰める。

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

### 通知メッセージ形式

- 開始通知（discussion）: 「🚀 **{ctf_name}** が開始しました!」+ 参加メンバーのメンション（下記チャンク分割）
- スナップショット（discussion）: 「🔒 **{ctf_name}** の募集が終了しました。」+「参加メンバー ({N}人):」+ メンションチャンク
- 参加通知（discussion）: 「🙋 {mention} が **{ctf_name}** に参加しました。」

### メンション分割

`MENTION_CHUNK_SIZE = 1700` 文字ごとに分割して複数メッセージで送信。Discord の 2000 文字制限にマージンを持たせている。

## データモデル

定義は `models.py` を正とする（このドキュメントに写しを持たない）。設計上のポイント:

- `ActiveCampaign` / `ClosedCampaign` は `Literal[CampaignStatus.*]` の discriminator を持つ状態別 dataclass で、`type Campaign = ActiveCampaign | ClosedCampaign` の union にまとめる（docs/design.md「状態依存データは型で表す」のパターン）
- `closed_at_unix` / `archive_at_unix` / `archived_at_unix` は `ClosedCampaign` のみが持つ
- DB decoder は status と nullable column の整合性を実行時に検証し、不正な行は `RepositoryError` にする。active 固有の query は `ActiveCampaign` を、closed 固有の query は `ClosedCampaign` を返す
- `CampaignDraft` は parse 済み入力（`ctf_name`, `start_at_unix`, `end_at_unix: int | None`）を表す Discord/DB 非依存モデル

## DB スキーマ

テーブル `ctf_team_campaign` の DDL は `db.py` の `_SCHEMA_DDL` を正とする（このドキュメントに写しを持たない）。設計上のポイント:

- `ctf_name` は `COLLATE NOCASE` で大文字小文字無視
- `(guild_id, ctf_name)` に partial unique index（`WHERE status = 'active'`）で同名 active 重複を防ぐ
- `(guild_id, message_id)` に UNIQUE 制約。リアクションからの逆引きには `(guild_id, channel_id, message_id, status)` の index を使う

## 関連設定

| 環境変数 | 必須 | 説明 |
|---|---|---|
| `CTF_TEAM_CATEGORY_ID` | Yes | 募集メッセージ・discussion・voice を作成するカテゴリ |
| `CTF_TEAM_ARCHIVE_CATEGORY_ID` | Yes | archive 時の discussion 移動先カテゴリ |

## 定数

| 定数 | 値 | 説明 |
|---|---|---|
| `MAX_ACTIVE_PER_USER` | 5 | 同一ユーザーの active 募集上限 |
| `MAX_CTF_NAME_LENGTH` | 60 | CTF 名の最大文字数 |
| `ARCHIVE_DELAY_DAYS` | 30 | close から archive までの日数 |
| `INPUT_DATETIME_FORMAT` | `%Y-%m-%d %H:%M` | 日時入力形式 |
| `REACTION_EMOJI` | ✅ | 参加リアクション |
| `ROLE_ANNOUNCE_CHANNEL_NAME` | `role` | 募集メッセージの投稿先チャンネル名 |
