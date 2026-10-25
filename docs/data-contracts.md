# データ・設定契約

設定変更・モデル変更・DB 移行の際に参照する。型宣言・SQL・メソッドのシグネチャは [config.py](../src/ctfbot/config.py) と [db.py](../src/ctfbot/db.py) に置き、本書は入力規則・不変条件・永続化の保証を記す。対応する検証は [test_config.py](../tests/test_config.py) と [test_db.py](../tests/test_db.py)。

## 設定契約（環境変数）

`load_settings`（`config.py`）が起動時に全項目を検証し、違反は `ConfigurationError` で起動拒否する（fail-fast）。[.env.example](../.env.example)・本表・実装を同じ変更で更新する。

### 読み取り規則

| 種別 | 規則 |
|---|---|
| 必須文字列 | strip 後に空なら起動拒否（デフォルトへのフォールバックはしない） |
| デフォルト付き文字列 | strip し、未設定・空文字はデフォルト値へフォールバック |
| ID・件数系（`_read_int`） | 未設定・空文字はデフォルト（デフォルト無しの変数は起動拒否）。整数でない値（空白のみを含む）・負値は起動拒否。`0` は受理する |
| optional ID | `0` を未設定として `None` に正規化（`or None`）。内部では `T | None` で扱う |
| 必須 ID | さらに `> 0` を要求（`0` も起動拒否） |
| 期間・件数（`_require_positive`） | `>= 1` を要求 |
| 時刻（`_read_clock_time`） | 未設定はデフォルト。設定値は strip 後に `%H:%M` としてパースし、**空文字・空白のみ・形式不正は起動拒否**（文字列系と異なりデフォルトへフォールバックしない）。`TIMEZONE` の tzinfo を付与した `datetime.time` になる |

### 環境変数一覧

| 変数 | 用途 | 型（Settings） | 必須 | デフォルト | 検証・正規化 |
|---|---|---|---|---|---|
| `DISCORD_TOKEN` | Bot トークン | `str` | Yes | なし | 必須文字列 |
| `GUILD_ID` | bot を運用する唯一の guild（コマンド登録先） | `int` | Yes | なし | 必須 ID（`> 0`） |
| `CTFTEAM_CATEGORY_ID` | discussion・voice を配置するカテゴリ | `int \| None` | — | `0` | optional ID。CTFTEAM の 3 ID はすべて設定またはすべて未設定 |
| `CTFTEAM_ARCHIVE_CATEGORY_ID` | archive 時の discussion 移動先カテゴリ | `int \| None` | — | `0` | optional ID。同上 |
| `CTFTEAM_ROLE_CHANNEL_ID` | 募集メッセージの投稿先テキストチャンネル | `int \| None` | — | `0` | optional ID。同上 |
| `BOT_CHANNEL_ID` | コマンド実行ログ・管理者操作通知・sudo 自動剥奪通知・接続状態通知の送信先（`None` で無効） | `int \| None` | — | `0` | optional ID |
| `CTFTIME_CHANNEL_ID` | CTFtime 週次通知の送信先（`None` で無効） | `int \| None` | — | `0` | optional ID |
| `ALPACAHACK_CHANNEL_ID` | AlpacaHack Daily・週次通知の送信先（`None` で無効） | `int \| None` | — | `0` | optional ID |
| `ALPACAHACK_MENTION_ID` | AlpacaHack Daily 通知でメンションする guild 内ユーザーまたはロール（`None` で無効） | `int \| None` | — | `0` | optional ID。ロールを優先して解決し、見つからなければメンバーを解決 |
| `TIMES_CATEGORY_ID` | `/times create` の作成先カテゴリ（`None` で times 機能無効） | `int \| None` | — | `0` | optional ID |
| `ADMIN_ROLE_ID` | `/sudo` で一時付与する管理者ロール | `int \| None` | — | `0` | optional ID。`SUDOER_ROLE_ID` と**両方設定または両方未設定**（片方だけは起動拒否）。**同一のロール ID は起動拒否**（理由は [docs/features/sudo.md](features/sudo.md)） |
| `SUDOER_ROLE_ID` | `/sudo` の実行を許可するロール | `int \| None` | — | `0` | optional ID。同上のペア制約・同一値拒否 |
| `SUDO_DURATION_MINUTES` | 昇格の有効時間（分） | `int` | — | `30` | `_require_positive` |
| `TIMEZONE` | 日時の解釈・表示のタイムゾーン | `tzinfo: ZoneInfo` | — | `Asia/Tokyo` | デフォルト付き文字列。`ZoneInfo` で解決できなければ起動拒否 |
| `LOG_LEVEL` | ログレベル | `str` | — | `INFO` | デフォルト付き文字列 |
| `DATABASE_PATH` | SQLite DB のパス | `str` | — | `ctfbot.db` | デフォルト付き文字列。親ディレクトリが存在しなければ起動拒否 |
| `ALPACAHACK_DAILY_TIME` | Daily AlpacaHack の新着確認時刻 | `datetime.time` | — | `00:05` | 時刻 |
| `ALPACAHACK_SOLVE_TIME` | 週次 solve 集計の実行時刻（日曜のみ実行） | `datetime.time` | — | `23:00` | 時刻 |
| `CTFTIME_NOTIFICATION_TIME` | CTFtime 週次通知の実行時刻（月曜のみ実行） | `datetime.time` | — | `09:00` | 時刻 |
| `CTFTIME_WINDOW_DAYS` | 取得するイベント期間（日数） | `int` | — | `14` | `_require_positive` |
| `CTFTIME_EVENT_LIMIT` | 取得するイベント数上限 | `int` | — | `20` | `_require_positive` |
| `CTFTIME_USER_AGENT` | CTFtime API リクエストの User-Agent | `str` | — | `ctfbot/2.0 (+discord)` | デフォルト付き文字列 |
| `TTS_VOICEVOX_URL` | VOICEVOX ENGINE のベース URL（`None` で VC 読み上げ無効）。設定すると `Settings.tts_enabled` が真になり、Message Content Intent が有効になる | `str \| None` | — | なし（機能無効） | strip 後に空なら `None` |
| `TTS_SPEAKER_IDS` | 自動割り当てに使う VOICEVOX の style ID のプール（順序が割り当ての巡回順）。変更すると自動の割り当てが変わる | `tuple[int, ...]` | — | `3,2,8,11,14,13` | カンマ区切り。各要素は strip した非負整数。未設定・空文字・空白のみはデフォルト。空の要素・整数でない値・負値は起動拒否。重複は最初の出現を残す。ENGINE に存在するかは起動時に検証しない |
| `TTS_MAX_CHARS` | 1 投稿あたりの読み上げ文字数 | `int` | — | `200` | `_require_positive`。`1000` を超えたら起動拒否 |
| `TTS_SPEED_SCALE` | 読み上げの話速。`audio_query` の `speedScale` を上書きする。変更は再起動で反映 | `float` | — | `2.0` | strip 後に空ならデフォルト。`float()` で解釈できない値・`nan`・`inf`・`0.5` 以上 `2.0` 以下を外れる値は起動拒否（既定値に戻さない） |

### Settings

`load_settings()` が返す dataclass。フィールドは上の環境変数一覧と 1 対 1 で、`TIMEZONE` のみ変換後の `tzinfo: ZoneInfo` として保持する。宣言は `src/ctfbot/config.py` を参照する。

## データモデル

### ctfteam（`features/ctfteam/models.py`）

`CampaignStatus`（`active` / `closed` の Enum）、状態別の `ActiveCampaign` と `ClosedCampaign`、その union である `type Campaign`、parse 済み入力を表す `CampaignDraft` を定義する。`status` は `Literal[CampaignStatus.*]` で discriminator になる。

invariant（DB decoder が実行時に検証し、違反行は `RepositoryError` にする）:

- active 行は `closed_at_unix`・`archive_at_unix`・`archived_at_unix` がすべて NULL
- closed 行は `closed_at_unix`・`archive_at_unix` が非 NULL（`archived_at_unix` は未 archive なら NULL）
- `end_at_unix` が NULL の campaign は常設（終了期限なし）
- `discussion_channel_id`・`voice_channel_id` は decoder で `0` を `None` に正規化する

### sudo（`features/sudo/models.py`）

`SudoGrant` を定義する。`role_id` は付与時点の `ADMIN_ROLE_ID` を保存する（grant 有効中の設定変更を反映しない。理由は [docs/features/sudo.md](features/sudo.md)）。

### ctftime（`features/ctftime.py`）

`CTFEvent` を定義する。`start`・`finish` は `Settings.tzinfo` へ変換済みの aware datetime。`ctftime_url` は取得できなければ `""`。

### alpacahack（`features/alpacahack/service.py`）

`SolveRecord` と、その週次集計である `WeeklySolveSummary`、Daily 問題を表す `DailyChallenge` を定義する。`solved_at`・`starts_at`・`ends_at` は `Settings.tzinfo` へ変換済みの aware datetime。`weekly_solves` のキーは username。取得に失敗したユーザーは `weekly_solves` に含めず `failed_users` にのみ入れる。

## DB スキーマ

DDL は `db.py` の `_SCHEMA_DDL`、移行 SQL は `_MIGRATIONS`、対応する最新版は `CURRENT_SCHEMA_VERSION` を参照する。列順を含め実行される SQL を確認し、文書へ複製しない。

| テーブル | 保存対象・一意性 |
|---|---|
| `alpacahack_user` | 登録名。一意な `name` |
| `alpacahack_daily_notification` | 通知済み challenge URL。URL を主キーとする |
| `ctfteam_campaign` | 募集と状態。`message_id` は一意、active の CTF 名は重複不可 |
| `audit_log_entry` | Discord 監査ログ。`entry_id` は一意、検索用に guild と発生時刻の index を持つ |
| `sudo_grant` | bot が管理する期限付きロール。`user_id` ごとに 1 件 |
| `tts_voice_preference` | VC 読み上げで `/read voice set` が選んだ声（VOICEVOX の style ID）。`user_id` ごとに 1 件。自動割り当ての声は保存しない |

CTF 名の `COLLATE NOCASE` は ASCII の大文字小文字だけを同一視する。非 ASCII の名前は大文字小文字を区別する。

### マイグレーション

スキーマ変更では `_SCHEMA_DDL` を更新し、`CURRENT_SCHEMA_VERSION` を 1 増やして `_MIGRATIONS` に N → N+1 の SQL を追加する。新規 DB と旧 DB の移行、同一移行の再実行を確認する。

| 移行 | 変更の意図 |
|---|---|
| 1 → 2 | Discord 監査ログの保存 |
| 2 → 3 | 一時昇格の追跡 |
| 3 → 4 | 単一 guild 運用に合わせ、募集・sudo の guild 区分を削除 |
| 4 → 5 | `ctf_team_campaign` を `ctfteam_campaign` へ改名 |
| 5 → 6 | Daily 通知の重複防止 |
| 6 → 7 | 開始・archive の期日検索と作成者別 active 件数の index |
| 7 → 8 | VC 読み上げの声の設定 |

テーブル再構築はトランザクション内で新テーブルへ明示した列をコピーする。募集の ID は維持し、index は最後の `_SCHEMA_DDL` 適用で復元する。

3 → 4 は複数 guild のデータが新しい一意制約に衝突する場合、統合せず起動を拒否する。4 → 5 は旧名・新名の存在しない側を空テーブルとして補い、両方からコピーするため、改名前後のどちらからも再実行できる。

### 起動時のスキーマ検証・移行手続き

`Database.__init__` が同期的に実行する。拒否はすべて `RepositoryError` で、bot は起動しない。

1. `PRAGMA user_version` を読む
2. **version 0 かつユーザーテーブルが存在** → 拒否（`Unmanaged database schema.`。バージョン管理外の DB）
3. **version > CURRENT_SCHEMA_VERSION** → 拒否（bot より新しい DB）
4. version 0（空 DB）→ `_SCHEMA_DDL` を一括適用し `user_version = CURRENT_SCHEMA_VERSION`
5. それ以外 → version が CURRENT に達するまで `_MIGRATIONS[version]` を順に適用し、1 段ごとに `user_version` を更新して commit。**移行パスが無い version は拒否**
6. 最後に `_SCHEMA_DDL` を冪等適用する（`IF NOT EXISTS`）

移行スクリプトの適用と `user_version` 更新は atomic ではない（`executescript` は実行前に暗黙 commit する）。クラッシュ時は同じスクリプトが再実行されるため、**移行スクリプトは再実行に耐える形で書く**（DDL は `IF NOT EXISTS`。UPDATE・データ変換を含む移行は冪等な述語を付ける）。

## Database API

`Database`（`db.py`）の契約。

### 共通契約

- 全メソッドは同期。イベントループ上からは `asyncio.to_thread` で呼ぶ
- 接続は**メソッド呼び出しごとに新規作成して close** する（共有接続を持たない。スレッド間の接続共有問題を構造的に回避する）
- 接続ごとに適用: `PRAGMA foreign_keys = ON` / `journal_mode = WAL` / `synchronous = NORMAL` / `busy_timeout = 5000`（ms）。`sqlite3.connect(timeout=10.0)`
- `sqlite3.Error` は `RepositoryError` に変換して raise する。例外時は未コミットの変更を残さない（接続 close によりロールバック）
- トランザクションはメソッド内で完結する（複数メソッドをまたぐトランザクションは提供しない）

### alpacahack_user

| メソッド | 契約 |
|---|---|
| `add_alpacahack_user` | `name.strip()` して挿入。strip 後空は `RepositoryError`。`BEGIN IMMEDIATE` で同名存在 → `False`、`COUNT(*) >= max_users`（新規名）→ `ConflictError("AlpacaHack user limit reached.")`、それ以外は挿入して `True` |
| `delete_alpacahack_user` | `name.strip()` で削除。`True`=削除、`False`=不在 |
| `list_alpacahack_users` | `name` 昇順の全件 |

### alpacahack_daily_notification

| メソッド | 契約 |
|---|---|
| `reserve_alpacahack_daily_notification` | challenge URL を通知済みとして挿入。新規なら `True`、既存なら変更せず `False`。通知送信より先に呼び、重複送信を防ぐ |

### audit_log_entry

| メソッド | 契約 |
|---|---|
| `insert_audit_log_entry` | 挿入したら `True`、**`entry_id` 重複のみ**を無視して `False`。それ以外の制約違反は `RepositoryError` として観測可能でなければならない（`INSERT ... ON CONFLICT(entry_id) DO NOTHING`） |

### sudo_grant

| メソッド | 契約 |
|---|---|
| `upsert_sudo_grant` | `ON CONFLICT (user_id) DO UPDATE` で **`role_id`・`expires_at_unix` のみ更新**（`granted_at_unix` は初回値を維持）。更新後の行を返す |
| `get_sudo_grant` | 主キー一致の 1 件 |
| `delete_sudo_grant` | 不在でも成功（冪等） |
| `list_expired_sudo_grants` | `expires_at_unix <= now` を `expires_at_unix` 昇順で全件 |

### tts_voice_preference

単一 guild 運用のため `guild_id` は持たない。guild を抜けたユーザーの行も消さない。戻り値は `int`・`bool` のみで、tts に `models.py` は置かない。

| メソッド | 契約 |
|---|---|
| `find_tts_voice` | 保存済みの style ID。なければ `None` |
| `upsert_tts_voice` | `ON CONFLICT (user_id) DO UPDATE` で `speaker_id`・`updated_at_unix` を更新。`speaker_id` は 0 以上（CHECK 違反は `RepositoryError`） |
| `delete_tts_voice` | 削除したら `True`、なければ `False` |

### ctfteam_campaign

`list_due_*` と `list_campaigns` の取得上限は既定 20 件。検索で見つからない場合は `None`、一覧は空リストを返す。

状態と query の述語:

| 論理状態 | DB 述語 |
|---|---|
| active | `status = 'active'` |
| closed（未 archive） | `status = 'closed' AND archived_at_unix IS NULL` |
| archived | `status = 'closed' AND archived_at_unix IS NOT NULL` |

| メソッド | 契約 |
|---|---|
| `count_active_campaigns_by_creator` | active の件数 |
| `has_active_campaign_with_name` | 同名 active の存在（`COLLATE NOCASE` 比較） |
| `create_campaign` | `BEGIN IMMEDIATE` で作成者の active 件数を再カウントし、`>= max_active_per_creator` なら `ConflictError("Active campaign limit reached.")`。同名 active の unique index 違反（`sqlite3.IntegrityError`）は `ConflictError("Active campaign already exists.")`。成功時は挿入行を返す |
| `find_active_campaign_by_message` | リアクションからの逆引き |
| `find_active_campaign_by_name` | 同名 active（`created_at_unix` 降順の最新 1 件） |
| `find_closed_campaign_by_name` | `archived=True` は archived のみ、`False` は未 archive の closed のみ、`None` は両方。`created_at_unix` 降順の最新 1 件 |
| `list_due_campaigns` | 自動 close 対象: `status='active' AND end_at_unix IS NOT NULL AND end_at_unix <= now`。`end_at_unix` 昇順（期日の古い順に処理し飢餓を防ぐ） |
| `list_due_starts` | 開始通知対象: `status='active' AND start_notified_at_unix IS NULL AND start_at_unix <= now`。**active 限定**（close 済みには通知しない）。`start_at_unix` 昇順 |
| `mark_started` | `WHERE start_notified_at_unix IS NULL AND status='active'` 条件付き UPDATE による atomic claim（active 限定。close と競合しても closed 行を claim しない）。`True`=claim 成功 |
| `close_campaign` | `WHERE status='active'` 条件付き UPDATE による atomic claim（active → closed 遷移）。`True`=実際に遷移した |
| `list_due_archives` | 自動 archive 対象: `status='closed' AND archive_at_unix <= now AND archived_at_unix IS NULL`。`archive_at_unix` 昇順 |
| `mark_archived` | `WHERE archived_at_unix IS NULL` 条件付き UPDATE による atomic claim。`True`=claim 成功 |
| `list_campaigns` | `status=None` は全件。`created_at_unix` 降順。`CLOSED` 指定は archived を含む（上記述語表を参照） |

### decoder 契約

- status 固有 query（`find_active_*`・`list_due_*` 等）は対応する具体型を返し、`list_campaigns` のみ union（`Campaign`）を返す
- decoder はデータモデル節の invariant を実行時検証し、違反行を `RepositoryError` にする
