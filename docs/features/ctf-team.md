# CTF 募集管理 (ctfteam)

`/ctfteam` コマンドグループで CTF 参加者の募集を管理する。募集の作成・一覧・終了・アーカイブのライフサイクルを持つ。コマンド応答はすべて ephemeral。

実装: [cog.py](../../src/ctfbot/features/ctfteam/cog.py)・[campaign.py](../../src/ctfbot/features/ctfteam/campaign.py)・[discord_ops.py](../../src/ctfbot/features/ctfteam/discord_ops.py)。入力・競合の検証は [test_campaign.py](../../tests/test_campaign.py)、各操作は `tests/test_ctfteam_*.py` を参照する。応答の正確な文面は各実装を参照し、本書では条件と結果を記す。

CTFTEAM の 3 ID がすべて未設定の場合は機能を無効として起動を許可する。`/ctfteam open` は設定不足を案内して中断する。3 ID の一部だけが設定された状態は起動時の設定検証で拒否する。

## ライフサイクル

```
active ──(end_at_unix 到達 or /ctfteam close)──→ closed ──(archive_at_unix 到達 or /ctfteam archive)──→ archived
```

DB の `status` は `'active'` / `'closed'` の 2 値のみ。archived は独立した status ではなく、closed 行の `archived_at_unix` が非 NULL であることで表現する。

### active 状態

- 募集メッセージが募集チャンネル（`CTFTEAM_ROLE_CHANNEL_ID`）に投稿されている
- リアクション (✅) でロール付与が行われる
- discussion / voice チャンネルが存在する

### closed 状態

- 募集メッセージに `🔒 **この募集は終了しました。**` ヘッダーが追加される
- voice チャンネルは削除される
- discussion チャンネルに参加メンバースナップショットが投稿される
- `archive_at_unix` = `closed_at_unix` + `ARCHIVE_DELAY_DAYS` 日が設定される（上限と時刻を参照）

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

close と同じく「Discord リソース → DB → 通知」の順で行う。archive カテゴリ（`settings.ctfteam_archive_category_id`）が解決できなければその時点で失敗（DB 未更新、リトライ対象）。それ以外のリソース操作は途中で失敗しても最後まで試行し、**すべて成功した場合のみ** DB を更新する:

1. discussion チャンネルの archive（`NotFound` は成功扱い）: archive カテゴリへの移動と権限更新を一度の編集で行う。`@everyone` を読み取り専用にし、募集ロールと作成者の overwrite を削除する。bot の overwrite は維持し、`manage_channels` を付与する
2. voice チャンネルが残っていれば削除（`NotFound` は成功扱い）
3. ロールを削除（既に存在しなければ成功扱い）
4. `mark_archived`（`archived_at_unix IS NULL` 条件付き UPDATE による atomic claim）で DB に記録
5. **4 で claim に成功した場合のみ**、discussion チャンネルが TextChannel として解決できていれば archive 完了を `send_safely` で通知する。送信失敗は archive を巻き戻さない（DB が正）

## コマンド

### `/ctfteam open ctf_name [role_color]`

`role_color` は 9 色のプリセットから選ぶ。省略時は青。選択肢と Modal のラベル・文面は cog の定義を参照する。不正な色は Modal を開く前に拒否する。

1. Modal で開始日時（必須）と終了日時（任意）を受け取る。いずれも最大 16 文字
2. 入力パース（`campaign.parse_campaign_draft`。日時は `settings.tzinfo` の naive 時刻として解釈する。DST を持つタイムゾーンで存在しない・二重に存在する時刻は ZoneInfo の既定（fold=0）で解決し、拒否しない）→ 作成可否確認（`campaign.ensure_campaign_can_be_created`）
3. ロール作成（名前 = CTF 名、指定色、mentionable）→ discussion チャンネル作成 → voice チャンネル作成 → 募集メッセージ送信（`allowed_mentions` はロールのみ許可）→ ✅ リアクション追加
4. DB に campaign レコード作成
5. 作成者にロール付与（既に保持していればスキップ — 手順 3 の ✅ リアクション追加以降に作成者自身のリアクションをハンドラが先に処理した場合等に成立する競合対策。作成者が member cache から解決できない場合は付与自体を行わない）
6. 開始時刻が既に過ぎていれば即座に開始通知（下記 claim 機構経由）

手順 4 の DB insert 成功をもって募集作成は成功とする。

**DB insert 成功前（手順 1〜4）の失敗**は作成済み Discord リソースをロールバック（`discord_ops.cleanup_resources`。DB は対象外）:

- `ServiceError` → メッセージをそのまま表示
- `ConflictError` → 同名募集または作成数上限による競合を案内
- その他の例外 → exception ログ + 作成失敗を案内

**DB insert 成功後（手順 5〜6）の失敗**は募集を巻き戻さない（`cleanup_resources` は実行しない）:

- 手順 5 のロール付与失敗（`discord.Forbidden`・`discord.HTTPException`）→ warning ログを記録し、成功応答に付与失敗と ✅ リアクションで参加できることを追記
- 手順 6 の即時開始通知の失敗 → ログのみ（送信失敗は warning、claim の例外は traceback 付き exception）。claim 未達なら毎分ループの `start_due_campaigns` が回収する

成功時は作成した募集名を応答し、CTF 名をコマンド実行ログに記録する。

DB insert（`create_campaign`）は DB レベルでも作成者の active 募集数と同名 active を再チェックし、違反は `ConflictError` を raise する（契約は [docs/data-contracts.md](../data-contracts.md)）。手順 2 の事前確認とこの再チェックの二段構えで、同時実行の競合を防ぐ。

入力・作成条件に違反した場合は、理由を案内して拒否する。

| 対象 | 受理条件 |
|---|---|
| CTF 名 | 空白正規化後に空でなく、最大文字数以内 |
| 日時 | `YYYY-MM-DD HH:MM` 形式 |
| 終了日時 | 省略可（常設）。指定する場合は開始日時より後 |
| 作成者 | active 募集数が上限未満 |
| 同名募集 | active に存在しない。大文字小文字の比較範囲は [DB の契約](../data-contracts.md#db-スキーマ) に従う |

文字数・件数の上限は「上限と時刻」を参照する。

### `/ctfteam list [status]`

status: `active`（デフォルト）, `closed`, `all`。Choice 表示名は「募集中」「終了」「すべて」。`closed`・`all` は archive 済みも含む（表示上は区別されない）。

Embed で対象の状態と取得件数を表示する。0 件なら該当する募集がないことを案内する。取得上限は `list_campaigns` の limit（[DB の契約](../data-contracts.md#ctfteam_campaign)）。募集ごとのブロックを作成日時の降順・空行区切りで列挙する。

各ブロックには募集名・状態・開始/終了日時・募集メッセージへのリンク・議論/VC/ロール・作成者を表示する。終了日時がなければ「常設」、チャンネルがなければ「-」。closed 行には archive 予定も表示する。

description の 4096 文字上限を超えるブロック以降は載せず、未表示件数を追加して打ち切る。省略行を含めて 4096 文字に収まるよう、省略行の分の余白を確保する。

### `/ctfteam close ctf_name`

権限は作成者または `manage_guild` 保持者に限定する。active の募集がない場合、権限がない場合は、それぞれ理由を案内して中断する。

リソース操作が失敗した場合は DB を更新せず、終了できなかったことを応答する。成功時は募集名と archive 予定日時を応答し、CTF 名をコマンド実行ログに記録する。

自動 close と競合して DB claim に負けた場合も、既に終了していれば成功応答を返す。スナップショットは claim に成功した側だけが送る。

### `/ctfteam archive ctf_name`

権限は close と同じ。権限不足、まだ active、既に archived、不在を区別して理由を案内する。active の場合は先に close するよう案内する。

リソース操作が失敗した場合は DB を更新せず、その旨を応答する。成功時は募集名と archive 完了を応答し、CTF 名をコマンド実行ログに記録する。

自動 archive と競合して DB claim に負けた場合も成功応答を返す。archive 通知は claim に成功した側だけが送る。

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

各タスクの対象取得は期日（`start_at_unix` / `end_at_unix` / `archive_at_unix`）の古い順に、1 分あたり `list_due_*` の limit 件（[docs/data-contracts.md](../data-contracts.md)）ずつ。処理しきれなかった分は翌分に最古から再試行される。

リソース操作の失敗は warning ログを記録して翌分リトライし続ける（打ち切りなし）。`Forbidden` 等の恒久的失敗は毎分記録されるこの warning ログで検知し、権限を修正して解消する。

開始通知は二重送信防止のため claim 機構を通す: `mark_started` が `start_notified_at_unix IS NULL AND status='active'` 条件付き UPDATE で atomic に claim し（close と競合しても closed 行を claim しない）、claim に成功した呼び出しだけが通知を送信する。`/ctfteam open` 直後の即時通知と毎分ループの両方が同じ claim を通る。

## Discord リソース操作 (discord_ops.py)

### boundary 関数

- `require_category`: `settings.ctfteam_category_id` をカテゴリとして解決し、不在・型違いは拒否する
- `require_role_channel`: `settings.ctfteam_role_channel_id` のチャンネルをテキストチャンネルとして解決する。不在・テキストチャンネル以外は拒否する。CTF募集カテゴリ内にある必要はない

### チャンネル名の正規化

`normalize_channel_name`: lowercase、Unicode 英数字と `-` 以外を `-` に置換、連続 `-` を 1 つにし、先頭末尾 `-` を除去して 100 文字に切り詰める。結果が空なら `"ctf"` にフォールバックする。

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

- `@everyone`: `view_channel=True`, `read_message_history=True`。メッセージ・スレッド内投稿・スレッド作成・ボイスメッセージ・投票・リアクションは禁止する
- 募集ロールと作成者個人の overwrite は削除する。個人への投稿許可は `@everyone` の投稿禁止より優先されるため、作成者も削除対象とする。作成者は保存済み ID で識別し、退出済み・メンバーキャッシュに不在でも削除する
- bot の投稿権限は通知用に維持し、`manage_channels` を付与する

### メッセージと通知

募集メッセージには CTF 名、開始・終了日時、discussion とロールへのメンション、✅ による参加案内を載せる。常設では終了日時を「常設」と表示する。募集ロールの ping を許可する。

discussion には開始通知・終了時の参加メンバースナップショット・ロール付与後の参加通知を送る。正確な文面は `discord_ops.py`、表示と権限の検証は [test_discord_ops.py](../../tests/test_discord_ops.py) を参照する。

参加メンバーはロール保持者（member cache。`Intents.members` 前提）で、列挙順は保証しない。0 人ならヘッダーのみ送る（スナップショットは人数表示まで）。ヘッダーはメンションを抑止し、メンバー列挙チャンクは users のみ許可する。共通の [メンション方針](../core.md#メンションと表示) に従う。

### メンション分割

`MENTION_CHUNK_SIZE`（上限と時刻を参照）ごとに分割して複数メッセージで送信。Discord の 2000 文字制限にマージンを持たせている。

## 上限と時刻

| 実装の定数 | 値 | 用途 |
|---|---|---|
| `MAX_ACTIVE_PER_USER` | 5 | 同一ユーザーの active 募集上限 |
| `MAX_CTF_NAME_LENGTH` | 60 | CTF 名の最大文字数 |
| `ARCHIVE_DELAY_DAYS` | 30 | close から archive までの日数 |
| `INPUT_DATETIME_FORMAT` | `%Y-%m-%d %H:%M` | 日時入力形式 |
| `REACTION_EMOJI` | ✅ | 参加リアクション |
| `MENTION_CHUNK_SIZE` | 1700 | メンション分割の 1 メッセージ上限 |

## 対象外

- ✅ リアクション解除によるロール剥奪・脱退処理（リアクションを外してもロールは維持される。脱退はロールの手動削除で行う）
