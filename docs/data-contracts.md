# データ・設定契約 (data-contracts)

この文書は **設定（環境変数・Settings）・データモデル・DB スキーマ・Database API の正本**である。実装がこの文書と乖離した場合は原則として実装をこの文書へ合わせる。仕様変更が妥当な場合は、先にこの文書を更新してから実装を追随させる。

スキーマ・モデルの変更手順は `AGENTS.md`「実装パターン」手順 8 に従い、変更と同時にこの文書を更新する。

## 設定契約（環境変数）

`load_settings`（`config.py`）が起動時に全項目を検証し、違反は `ConfigurationError` で起動拒否する（fail-fast）。`.env.example` はこの表と同期させる（この表が正本）。

### 読み取り規則

| 種別 | 規則 |
|---|---|
| 必須文字列 | strip 後に空なら起動拒否（デフォルトへのフォールバックはしない） |
| デフォルト付き文字列 | strip し、未設定・空文字はデフォルト値へフォールバック |
| ID・件数系（`_read_int`） | 未設定・空文字はデフォルト（デフォルト無しの変数は起動拒否）。整数でない値（空白のみを含む）・負値は起動拒否。`0` は受理する |
| optional ID | `0` を未設定として `None` に正規化（`or None`）。内部では `T | None` で扱う（design.md「sentinel は入口で正規化する」） |
| 必須 ID | さらに `> 0` を要求（`0` も起動拒否） |
| 期間・件数（`_require_positive`） | `>= 1` を要求 |
| 時刻（`_read_clock_time`） | 未設定はデフォルト。設定値は strip 後に `%H:%M` として厳密にパースし、**空文字・空白のみ・形式不正は起動拒否**（文字列系と異なりデフォルトへフォールバックしない）。`TIMEZONE` の tzinfo を付与した `datetime.time` になる |

### 環境変数一覧

| 変数 | 用途 | 型（Settings） | 必須 | デフォルト | 検証・正規化 |
|---|---|---|---|---|---|
| `DISCORD_TOKEN` | Bot トークン | `str` | Yes | なし | 必須文字列 |
| `CTF_TEAM_CATEGORY_ID` | `#role`（募集メッセージ投稿先）・discussion・voice を配置するカテゴリ | `int` | Yes | なし | 必須 ID（`> 0`） |
| `CTF_TEAM_ARCHIVE_CATEGORY_ID` | archive 時の discussion 移動先カテゴリ | `int` | Yes | なし | 必須 ID（`> 0`） |
| `BOT_CHANNEL_ID` | コマンド実行ログ・sudo 自動剥奪通知の送信先（`None` で無効） | `int \| None` | — | `0` | optional ID |
| `BOT_STATUS_CHANNEL_ID` | 接続状態通知の送信先（`None` で無効） | `int \| None` | — | `0` | optional ID |
| `CTFTIME_CHANNEL_ID` | CTFtime 週次通知の送信先（`None` で無効） | `int \| None` | — | `0` | optional ID |
| `ALPACAHACK_CHANNEL_ID` | AlpacaHack 週次通知の送信先（`None` で無効） | `int \| None` | — | `0` | optional ID |
| `ADMIN_ROLE_ID` | `/sudo` で一時付与する管理者ロール | `int \| None` | — | `0` | optional ID。`SUDOER_ROLE_ID` と**両方設定または両方未設定**（片方だけは起動拒否）。**同一のロール ID は起動拒否**（理由は `docs/features/sudo.md`） |
| `SUDOER_ROLE_ID` | `/sudo` の実行を許可するロール | `int \| None` | — | `0` | optional ID。同上のペア制約・同一値拒否 |
| `SUDO_DURATION_MINUTES` | 昇格の有効時間（分） | `int` | — | `30` | `_require_positive` |
| `TIMEZONE` | 日時の解釈・表示のタイムゾーン | `str` + `tzinfo: ZoneInfo` | — | `Asia/Tokyo` | デフォルト付き文字列。`ZoneInfo` で解決できなければ起動拒否 |
| `LOG_LEVEL` | ログレベル | `str` | — | `INFO` | デフォルト付き文字列 |
| `DATABASE_PATH` | SQLite DB のパス | `str` | — | `ctfbot.db` | デフォルト付き文字列。親ディレクトリが存在しなければ起動拒否 |
| `ALPACAHACK_SOLVE_TIME` | 週次 solve 集計の実行時刻（日曜のみ実行） | `datetime.time` | — | `23:00` | 時刻 |
| `CTFTIME_NOTIFICATION_TIME` | CTFtime 週次通知の実行時刻（月曜のみ実行） | `datetime.time` | — | `09:00` | 時刻 |
| `CTFTIME_WINDOW_DAYS` | 取得するイベント期間（日数） | `int` | — | `14` | `_require_positive` |
| `CTFTIME_EVENT_LIMIT` | 取得するイベント数上限 | `int` | — | `20` | `_require_positive` |
| `CTFTIME_USER_AGENT` | CTFtime API リクエストの User-Agent | `str` | — | `ctfbot/2.0 (+discord)` | デフォルト付き文字列 |

### Settings

```python
@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    bot_channel_id: int | None
    bot_status_channel_id: int | None
    ctf_team_category_id: int
    ctf_team_archive_category_id: int
    ctftime_channel_id: int | None
    alpacahack_channel_id: int | None
    admin_role_id: int | None
    sudoer_role_id: int | None
    sudo_duration_minutes: int
    timezone: str
    tzinfo: ZoneInfo
    log_level: str
    database_path: str
    alpacahack_solve_time: datetime.time
    ctftime_notification_time: datetime.time
    ctftime_window_days: int
    ctftime_event_limit: int
    ctftime_user_agent: str
```

## データモデル

全 dataclass は `frozen=True, slots=True`。discord に依存しない（アーキテクチャ制約）。

### ctf_team（`features/ctf_team/models.py`）

```python
class CampaignStatus(Enum):
    ACTIVE = "active"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class ActiveCampaign:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    role_id: int
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
    status: Literal[CampaignStatus.ACTIVE]
    created_by: int
    created_at_unix: int
    start_notified_at_unix: int | None = None
    discussion_channel_id: int | None = None
    voice_channel_id: int | None = None


@dataclass(frozen=True, slots=True)
class ClosedCampaign:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    role_id: int
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
    status: Literal[CampaignStatus.CLOSED]
    created_by: int
    created_at_unix: int
    closed_at_unix: int
    archive_at_unix: int
    archived_at_unix: int | None = None
    discussion_channel_id: int | None = None
    voice_channel_id: int | None = None


type Campaign = ActiveCampaign | ClosedCampaign


@dataclass(frozen=True, slots=True)
class CampaignDraft:
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
```

invariant（DB decoder が実行時に検証し、違反行は `RepositoryError` にする）:

- active 行は `closed_at_unix`・`archive_at_unix`・`archived_at_unix` がすべて NULL
- closed 行は `closed_at_unix`・`archive_at_unix` が非 NULL（`archived_at_unix` は未 archive なら NULL）
- `end_at_unix` が NULL の campaign は常設（終了期限なし）
- `discussion_channel_id`・`voice_channel_id` は decoder で `0` を `None` に正規化する
- `CampaignDraft` は parse 済み入力を表す Discord/DB 非依存モデル

### sudo（`features/sudo/models.py`）

```python
@dataclass(frozen=True, slots=True)
class SudoGrant:
    guild_id: int
    user_id: int
    role_id: int
    granted_at_unix: int
    expires_at_unix: int
```

`role_id` は付与時点の `ADMIN_ROLE_ID` を保存する（grant 有効中の設定変更を反映しない。理由は `docs/features/sudo.md`）。

### ctftime（`features/ctftime.py`）

```python
@dataclass(frozen=True, slots=True)
class CTFEvent:
    title: str
    start: datetime.datetime
    finish: datetime.datetime
    ctftime_url: str
```

`start`・`finish` は `Settings.tzinfo` へ変換済みの aware datetime。`ctftime_url` は取得できなければ `""`。

### alpacahack（`features/alpacahack.py`）

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
    weekly_solves: dict[str, list[SolveRecord]]
    failed_users: list[str]
```

`solved_at` は `Settings.tzinfo` へ変換済みの aware datetime。`weekly_solves` のキーは username。取得に失敗したユーザーは `weekly_solves` に含めず `failed_users` にのみ入れる。

### audit_log

dataclass は定義しない（書き込み専用で読み取りパスを持たないため。`docs/features/audit-log.md`）。

## DB スキーマ

`CURRENT_SCHEMA_VERSION = 3`。

### DDL（`_SCHEMA_DDL`）

```sql
CREATE TABLE IF NOT EXISTS alpacahack_user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS ctf_team_campaign (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    ctf_name TEXT NOT NULL COLLATE NOCASE,
    start_at_unix INTEGER NOT NULL,
    end_at_unix INTEGER,
    status TEXT NOT NULL CHECK (status IN ('active', 'closed')),
    created_by INTEGER NOT NULL,
    created_at_unix INTEGER NOT NULL,
    closed_at_unix INTEGER,
    discussion_channel_id INTEGER,
    archive_at_unix INTEGER,
    archived_at_unix INTEGER,
    start_notified_at_unix INTEGER,
    voice_channel_id INTEGER,
    UNIQUE (guild_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_campaign_guild_message
    ON ctf_team_campaign (guild_id, channel_id, message_id, status);
CREATE INDEX IF NOT EXISTS idx_campaign_status_end
    ON ctf_team_campaign (status, end_at_unix);
CREATE INDEX IF NOT EXISTS idx_campaign_guild_status
    ON ctf_team_campaign (guild_id, status, created_at_unix);
CREATE UNIQUE INDEX IF NOT EXISTS idx_campaign_active_name_unique
    ON ctf_team_campaign (guild_id, ctf_name)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS audit_log_entry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL UNIQUE,
    guild_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    user_id INTEGER,
    target_id INTEGER,
    reason TEXT,
    changes_json TEXT NOT NULL,
    extra_text TEXT,
    created_at_unix INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_guild_created
    ON audit_log_entry (guild_id, created_at_unix);

CREATE TABLE IF NOT EXISTS sudo_grant (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    granted_at_unix INTEGER NOT NULL,
    expires_at_unix INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_sudo_grant_expires
    ON sudo_grant (expires_at_unix);
```

注意: `COLLATE NOCASE` の case folding は **ASCII の 26 文字のみ**（SQLite 組み込みの制限）。非 ASCII の CTF 名は大文字小文字が区別される。

### マイグレーション

`_MIGRATIONS: dict[int, str]` に「version N から N+1 への移行 SQL スクリプト」を登録する。

```sql
-- 1 → 2
CREATE TABLE IF NOT EXISTS audit_log_entry ( ...上記 DDL と同一... );
CREATE INDEX IF NOT EXISTS idx_audit_log_guild_created
    ON audit_log_entry (guild_id, created_at_unix);

-- 2 → 3
CREATE TABLE IF NOT EXISTS sudo_grant ( ...上記 DDL と同一... );
CREATE INDEX IF NOT EXISTS idx_sudo_grant_expires
    ON sudo_grant (expires_at_unix);
```

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

- 全メソッドは同期。イベントループ上からは `asyncio.to_thread` で呼ぶ（AGENTS.md 制約 10）
- 接続は**メソッド呼び出しごとに新規作成して close** する（共有接続を持たない。スレッド間の接続共有問題を構造的に回避する）
- 接続ごとに適用: `PRAGMA foreign_keys = ON` / `journal_mode = WAL` / `synchronous = NORMAL` / `busy_timeout = 5000`（ms）。`sqlite3.connect(timeout=10.0)`
- `sqlite3.Error` は `RepositoryError` に変換して raise する。例外時は未コミットの変更を残さない（接続 close によりロールバック）
- トランザクションはメソッド内で完結する（複数メソッドをまたぐトランザクションは提供しない）

### alpacahack_user

| メソッド | 契約 |
|---|---|
| `add_alpacahack_user(name) -> bool` | `name.strip()` して挿入。strip 後空は `RepositoryError`。`True`=挿入、`False`=同名（UNIQUE）既存 |
| `delete_alpacahack_user(name) -> bool` | `name.strip()` で削除。`True`=削除、`False`=不在 |
| `list_alpacahack_users() -> list[str]` | `name` 昇順の全件 |

### audit_log_entry

| メソッド | 契約 |
|---|---|
| `insert_audit_log_entry(*, entry_id, guild_id, action, user_id, target_id, reason, changes_json, extra_text, created_at_unix) -> bool` | 挿入したら `True`、**`entry_id` 重複のみ**を無視して `False`。それ以外の制約違反は `RepositoryError` として観測可能でなければならない（`INSERT ... ON CONFLICT(entry_id) DO NOTHING`。現行実装の `INSERT OR IGNORE` は本契約へ追随する） |

### sudo_grant

| メソッド | 契約 |
|---|---|
| `upsert_sudo_grant(guild_id, user_id, role_id, granted_at_unix, expires_at_unix) -> SudoGrant` | `ON CONFLICT (guild_id, user_id) DO UPDATE` で **`role_id`・`expires_at_unix` のみ更新**（`granted_at_unix` は初回値を維持）。更新後の行を返す |
| `get_sudo_grant(guild_id, user_id) -> SudoGrant \| None` | 主キー一致の 1 件 |
| `delete_sudo_grant(guild_id, user_id) -> None` | 不在でも成功（冪等） |
| `list_expired_sudo_grants(now_unix) -> list[SudoGrant]` | `expires_at_unix <= now` を `expires_at_unix` 昇順で全件 |

### ctf_team_campaign

状態と query の述語（「closed」の二義性を解消する正本）:

| 論理状態 | DB 述語 |
|---|---|
| active | `status = 'active'` |
| closed（未 archive） | `status = 'closed' AND archived_at_unix IS NULL` |
| archived | `status = 'closed' AND archived_at_unix IS NOT NULL` |

| メソッド | 契約 |
|---|---|
| `count_active_campaigns_by_creator(guild_id, created_by) -> int` | active の件数 |
| `has_active_campaign_with_name(guild_id, ctf_name) -> bool` | 同名 active の存在（`COLLATE NOCASE` 比較） |
| `create_campaign(*, guild_id, channel_id, message_id, role_id, discussion_channel_id, voice_channel_id, ctf_name, start_at_unix, end_at_unix, created_by, created_at_unix, max_active_per_creator) -> ActiveCampaign` | `BEGIN IMMEDIATE` で作成者の active 件数を再カウントし、`>= max_active_per_creator` なら `ConflictError("Active campaign limit reached.")`。同名 active の unique index 違反（`sqlite3.IntegrityError`）は `ConflictError("Active campaign already exists.")`。成功時は挿入行を返す |
| `find_active_campaign_by_message(*, guild_id, channel_id, message_id) -> ActiveCampaign \| None` | リアクションからの逆引き |
| `find_active_campaign_by_name(*, guild_id, ctf_name) -> ActiveCampaign \| None` | 同名 active（`created_at_unix` 降順の最新 1 件） |
| `find_closed_campaign_by_name(*, guild_id, ctf_name, archived: bool \| None = None) -> ClosedCampaign \| None` | `archived=True` は archived のみ、`False` は未 archive の closed のみ、`None` は両方。`created_at_unix` 降順の最新 1 件 |
| `list_due_campaigns(now_unix, limit=20) -> list[ActiveCampaign]` | 自動 close 対象: `status='active' AND end_at_unix IS NOT NULL AND end_at_unix <= now`。`end_at_unix` 昇順（期日の古い順に処理し飢餓を防ぐ） |
| `list_due_starts(now_unix, limit=20) -> list[ActiveCampaign]` | 開始通知対象: `status='active' AND start_notified_at_unix IS NULL AND start_at_unix <= now`。**active 限定**（close 済みには通知しない）。`start_at_unix` 昇順 |
| `mark_started(campaign_id, started_at_unix) -> bool` | `WHERE start_notified_at_unix IS NULL` 条件付き UPDATE による atomic claim。`True`=claim 成功 |
| `close_campaign(campaign_id, closed_at_unix, archive_at_unix) -> bool` | `WHERE status='active'` 条件付き UPDATE による atomic claim（active → closed 遷移）。`True`=実際に遷移した |
| `list_due_archives(now_unix, limit=20) -> list[ClosedCampaign]` | 自動 archive 対象: `status='closed' AND archive_at_unix <= now AND archived_at_unix IS NULL`。`archive_at_unix` 昇順 |
| `mark_archived(campaign_id, archived_at_unix) -> bool` | `WHERE archived_at_unix IS NULL` 条件付き UPDATE による atomic claim。`True`=claim 成功 |
| `list_campaigns(guild_id, status: CampaignStatus \| None, limit=20) -> list[Campaign]` | `status=None` は全件。`created_at_unix` 降順。`CLOSED` 指定は archived を含む（上記述語表を参照） |

### decoder 契約

- status 固有 query（`find_active_*`・`list_due_*` 等）は対応する具体型を返し、`list_campaigns` のみ union（`Campaign`）を返す
- decoder はデータモデル節の invariant を実行時検証し、違反行を `RepositoryError` にする（不正な状態を decoder より内側へ持ち込まない。design.md「状態依存データは型で表す」）
