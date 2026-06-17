# ctfbot — Implementation Spec

## 設計判断

**`discord_ops.py` を ctf_team cog から分離する。**
Discord リソース操作（チャンネル作成、権限設定、archive 移動など）を standalone 関数に切り出す。関数シグネチャが依存を型で明示するため、暗黙の `self` 参照が発生しない。変更時に影響範囲が関数単位で閉じる。

**`alpacahack.py` は 1 ファイルに収める。**
スクレイパー、週次ロジック、cog を 1 ファイルにまとめる。約 400 行。「このファイルを修正して」で全体が完結する。

**validation は例外ベース。**
`ServiceError` を raise し、cog で `try/except ServiceError` の 1 パターンで統一する。新しいバリデーション項目追加時も `raise ServiceError("...")` を書くだけで呼び出し側の変更が不要。

**Database を 1 クラスに集約する。**
2 テーブル・15 メソッド。全 SQL が 1 ファイルに集まるため、新しいクエリの追加先に迷わない。

**BotRuntime は Settings + Database のみ持つ。**
API クライアントは各 cog の `__init__` でローカル生成する。feature 追加時に runtime の変更が不要。

**分割の基準は「型の境界」。**
Discord オブジェクト（`guild`, `role`, `channel`）を受け取る関数と、プリミティブ型のみで動く関数を別モジュールに分ける。後者は `asyncio.to_thread` 経由でも呼べるし、テストで Discord のモックが不要。

---

## 技術スタック

- Python 3.14+
- discord.py 2.x（`commands.Bot` + `app_commands`）
- SQLite（WAL mode）— blocking I/O は全て `asyncio.to_thread` 経由
- requests（同期 HTTP）
- BeautifulSoup4（HTML scraping）

```toml
[project]
name = "ctfbot"
version = "1.0.0"
requires-python = ">=3.14"
dependencies = [
    "beautifulsoup4>=4.14",
    "discord-py>=2.7",
    "python-dotenv>=1.2",
    "requests>=2.32",
]

[dependency-groups]
dev = ["ruff>=0.15", "ty>=0.0.22"]

[tool.ruff]
target-version = "py314"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "W", "N", "UP", "B", "C4", "SIM", "RUF"]

[tool.ty.environment]
root = ["./src"]
python = "./.venv"
python-version = "3.14"
```

---

## ディレクトリ構造

```
ctfbot/
├── pyproject.toml
├── .env.example
├── src/
│   ├── main.py
│   └── bot/
│       ├── __init__.py          # 空
│       ├── app.py               # CTFBot, BotRuntime, create_bot, run_bot
│       ├── cogs_loader.py       # DEFAULT_EXTENSIONS, load_cogs
│       ├── config.py            # Settings, load_settings
│       ├── db.py                # Database クラス（全テーブルの全 SQL）
│       ├── errors.py            # 例外階層
│       ├── log.py               # logger, configure_logging
│       ├── helpers.py           # Discord ユーティリティ
│       └── features/
│           ├── __init__.py      # 空
│           ├── ctf_team/
│           │   ├── __init__.py  # 空
│           │   ├── models.py
│           │   ├── campaign.py
│           │   ├── discord_ops.py
│           │   └── cog.py
│           ├── ctftime.py
│           ├── alpacahack.py
│           ├── times.py
│           └── utility.py
└── tests/
    ├── __init__.py
    ├── test_architecture.py
    ├── test_config.py
    ├── test_db.py
    ├── test_campaign.py
    ├── test_ctftime_client.py
    └── test_alpacahack.py
```

---

## 依存ルール

```
cog.py         → campaign.py, discord_ops.py, db.py, helpers.py
campaign.py    → db.py, errors.py, models.py
campaign.py    ✗ discord（import 禁止）
discord_ops.py → discord, helpers.py, models.py
discord_ops.py ✗ db.py（import 禁止）
alpacahack.py  → db.py, helpers.py
ctftime.py     → helpers.py
db.py          ✗ discord（import 禁止）
helpers.py     → discord

feature 間の相互 import は禁止（alpacahack ↔ ctftime ↔ ctf_team）。
```

`tests/test_architecture.py` で AST を使ってこのルールを検証する。

---

## `src/main.py`

```python
from bot.app import create_bot, run_bot

def main() -> None:
    bot = create_bot()
    run_bot(bot)

if __name__ == "__main__":
    main()
```

---

## `src/bot/errors.py`

```python
class BotError(Exception): ...
class ConfigurationError(BotError): ...
class RepositoryError(BotError): ...
class ConflictError(RepositoryError): ...
class ServiceError(BotError): ...
class ExternalAPIError(ServiceError): ...
```

| 例外 | 用途 | 処理 |
|---|---|---|
| `ServiceError` | ユーザー向けエラー。メッセージは日本語 | cog が catch → `send_interaction` で表示 |
| `RepositoryError` | DB 操作失敗 | ログに記録 |
| `ConflictError` | 一意制約違反（同名 campaign 等） | cog が catch → cleanup + エラー表示 |
| `ExternalAPIError` | 外部 API 呼び出し失敗 | ログに記録 + ユーザーにフォールバック応答 |
| `ConfigurationError` | 起動時の設定不備 | fail-fast（bot 起動しない） |

---

## `src/bot/log.py`

```python
import logging

logger = logging.getLogger("ctfbot")

def configure_logging(level: str) -> None:
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return
    logging.basicConfig(
        level=level,
        format="%(asctime)s:%(levelname)s:%(name)s: %(message)s",
    )
```

---

## `src/bot/config.py`

```python
@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str                         # DISCORD_TOKEN（必須）
    bot_channel_id: int                        # BOT_CHANNEL_ID（0=無効）— audit ログ送信先
    bot_status_channel_id: int                 # BOT_STATUS_CHANNEL_ID（0=無効）— 接続状態通知先
    ctf_team_category_id: int                  # CTF_TEAM_CATEGORY_ID（必須 >=1）— discussion/voice 作成先カテゴリ
    ctf_team_archive_category_id: int          # CTF_TEAM_ARCHIVE_CATEGORY_ID（必須 >=1）— archive 移動先カテゴリ
    ctftime_channel_id: int                    # CTFTIME_CHANNEL_ID（0=無効）— CTFtime 週次通知先
    alpacahack_channel_id: int                 # ALPACAHACK_CHANNEL_ID（0=無効）— AlpacaHack 週次通知先
    timezone: str                              # TIMEZONE（default "Asia/Tokyo"）
    tzinfo: ZoneInfo                           # timezone から派生（Settings フィールドだが env からは読まない）
    log_level: str                             # LOG_LEVEL（default "INFO"）
    database_path: str                         # DATABASE_PATH（default "ctfbot.db"）
    alpacahack_solve_time: datetime.time       # ALPACAHACK_SOLVE_TIME（default "23:00"）— 日曜のみ実行
    ctftime_notification_time: datetime.time   # CTFTIME_NOTIFICATION_TIME（default "09:00"）— 月曜のみ実行
    ctftime_window_days: int                   # CTFTIME_WINDOW_DAYS（default 14, >=1）
    ctftime_event_limit: int                   # CTFTIME_EVENT_LIMIT（default 20, >=1）
    ctftime_user_agent: str                    # CTFTIME_USER_AGENT（default "ctfbot/2.0 (+discord)"）
```

`load_settings(*, dotenv_path=None, environ=None) -> Settings`:
- `load_dotenv()` 後に `os.environ`（または `environ` 引数）から読む
- int フィールドは `_read_int(environ, name, default)` ヘルパーで読む。負の値は `ConfigurationError`
- time フィールドは `_read_clock_time(environ, name, default, tzinfo=tzinfo)` ヘルパーで読む。"HH:MM" 形式
- `discord_token` 欠落 → `ConfigurationError`
- `ctf_team_category_id` or `ctf_team_archive_category_id` が 0 以下 → `ConfigurationError`
- `database_path` の親ディレクトリ不在 → `ConfigurationError`
- `timezone` が `ZoneInfo` で解決不可 → `ConfigurationError`
- `tzinfo` は `ZoneInfo(timezone)` で生成

---

## `src/bot/db.py`

### Database クラス

```python
CURRENT_SCHEMA_VERSION = 1

_SCHEMA_DDL = """\
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
"""

# SELECT で使うカラム順。_to_campaign() と一致させること。
_CAMPAIGN_COLUMNS = (
    "id, guild_id, channel_id, message_id, role_id, ctf_name, "
    "start_at_unix, end_at_unix, status, created_by, created_at_unix, "
    "start_notified_at_unix, closed_at_unix, archive_at_unix, archived_at_unix, "
    "discussion_channel_id, voice_channel_id"
)

class Database:
    def __init__(self, path: str) -> None:
        self._path = str(Path(path).expanduser().resolve())
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=10.0)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            yield conn
        except sqlite3.Error as exc:
            raise RepositoryError(str(exc)) from exc
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        """PRAGMA user_version で管理。
        - 0 かつテーブルなし → DDL 実行 + user_version 設定
        - 0 かつテーブルあり → RepositoryError（未管理 DB）
        - version 不一致 → RepositoryError
        - version 一致 → OK
        """

    @staticmethod
    def _to_campaign(row: tuple) -> Campaign:
        """_CAMPAIGN_COLUMNS の順序でタプルを Campaign に変換。
        status は CampaignStatus(row[8]) で変換。"""
```

### メソッド一覧

```python
# --- AlpacaHack ---

def add_alpacahack_user(self, name: str) -> bool:
    """INSERT OR IGNORE。作成されたら True、既存なら False。
    name は strip() してから保存。空なら RepositoryError。"""

def delete_alpacahack_user(self, name: str) -> bool:
    """DELETE。削除されたら True、見つからなければ False。"""

def list_alpacahack_users(self) -> list[str]:
    """全ユーザーを ORDER BY name ASC で返す。"""

# --- Campaign ---

def count_active_campaigns_by_creator(self, guild_id: int, created_by: int) -> int:
    """WHERE guild_id=? AND created_by=? AND status='active'"""

def has_active_campaign_with_name(self, guild_id: int, ctf_name: str) -> bool:
    """WHERE guild_id=? AND ctf_name=? AND status='active'
    ctf_name カラムは COLLATE NOCASE なので自動的に大文字小文字無視。"""

def create_campaign(
    self, *, guild_id: int, channel_id: int, message_id: int,
    role_id: int, discussion_channel_id: int | None,
    voice_channel_id: int | None, ctf_name: str,
    start_at_unix: int, end_at_unix: int | None,
    created_by: int, created_at_unix: int,
) -> Campaign:
    """INSERT して Campaign を返す。
    INSERT 前に SELECT で同名 active 存在チェック → 存在すれば ConflictError。
    status='active' 固定。"""

def find_active_campaign_by_message(
    self, *, guild_id: int, channel_id: int, message_id: int,
) -> Campaign | None:
    """WHERE guild_id=? AND channel_id=? AND message_id=? AND status='active'"""

def find_campaign_by_name(
    self, *, guild_id: int, ctf_name: str,
    status: CampaignStatus,
    archived: bool | None = None,
) -> Campaign | None:
    """WHERE guild_id=? AND ctf_name=? AND status=?
    archived=True  → AND archived_at_unix IS NOT NULL
    archived=False → AND archived_at_unix IS NULL
    archived=None  → フィルタなし"""

def list_due_campaigns(self, now_unix: int, limit: int = 20) -> list[Campaign]:
    """WHERE status='active' AND end_at_unix IS NOT NULL AND end_at_unix <= ?
    ORDER BY end_at_unix ASC"""

def list_due_starts(self, now_unix: int, limit: int = 20) -> list[Campaign]:
    """WHERE status='active' AND start_notified_at_unix IS NULL AND start_at_unix <= ?
    ORDER BY start_at_unix ASC"""

def mark_started(self, campaign_id: int, started_at_unix: int) -> bool:
    """UPDATE SET start_notified_at_unix=? WHERE id=? AND start_notified_at_unix IS NULL
    rowcount > 0 なら True。"""

def close_campaign(self, campaign_id: int, closed_at_unix: int, archive_at_unix: int) -> bool:
    """UPDATE SET status='closed', closed_at_unix=?, archive_at_unix=?
    WHERE id=? AND status='active'
    rowcount > 0 なら True。"""

def list_due_archives(self, now_unix: int, limit: int = 20) -> list[Campaign]:
    """WHERE status='closed' AND archive_at_unix IS NOT NULL
    AND archive_at_unix <= ? AND archived_at_unix IS NULL
    ORDER BY archive_at_unix ASC"""

def mark_archived(self, campaign_id: int, archived_at_unix: int) -> bool:
    """UPDATE SET archived_at_unix=? WHERE id=? AND archived_at_unix IS NULL
    rowcount > 0 なら True。"""

def list_campaigns(self, guild_id: int, status: str | None, limit: int = 20) -> list[Campaign]:
    """status="active" or "closed" → WHERE フィルタ。None → 全件。
    ORDER BY created_at_unix DESC。LIMIT ?。"""
```

---

## `src/bot/helpers.py`

```python
async def send_safely(
    channel: discord.abc.Messageable,
    content: str | None = None,
    embed: discord.Embed | None = None,
    allowed_mentions: discord.AllowedMentions | None = None,
) -> discord.Message | None:
    """送信に失敗したら None を返す。HTTPException をキャッチしてログ。"""

async def send_interaction(
    interaction: discord.Interaction,
    content: str,
    ephemeral: bool = True,
) -> None:
    """response.is_done() を確認し:
    - False → interaction.response.send_message(content, ephemeral=ephemeral)
    - True  → interaction.followup.send(content, ephemeral=ephemeral)
    InteractionResponded / NotFound / HTTPException はログして無視。"""

def format_timestamp(value: int | float | datetime.datetime | None, *, style: str = "f") -> str:
    """None → "-"。
    datetime → int(timestamp())。
    返却: "<t:{unix}:{style}>"。"""

def format_timestamp_with_relative(value: int | None, *, style: str = "f") -> str:
    """None → "-"。
    返却: "<t:{unix}:{style}> (<t:{unix}:R>)"。"""

def sanitize_audit_text(value: object) -> str:
    """str(value) → 空白正規化 → '<@' を '<@​' に置換（メンション無効化）。"""

async def log_audit(
    bot: commands.Bot,
    interaction: discord.Interaction,
    *,
    command_name: str,
    details: Sequence[str] = (),
) -> None:
    """bot.runtime.settings.bot_channel_id が 0 以下なら何もしない。
    get_channel → fetch_channel でチャンネル解決。

    メッセージ形式:
    📝 `{display_name}` (id={user_id}) が #{channel_name} で `/{command_name}` を実行しました。
    - {details[0]}
    - {details[1]}
    ...

    最大 1900 文字。超過時は末尾を "..." で切る。
    allowed_mentions=AllowedMentions.none()。"""

async def resolve_messageable(
    bot: commands.Bot,
    channel_id: int,
) -> discord.abc.Messageable | None:
    """channel_id <= 0 → None。bot.get_channel(id) → 見つからなければ bot.fetch_channel(id)。
    NotFound / Forbidden → None。"""

async def fetch_member(
    guild: discord.Guild,
    user_id: int,
) -> discord.Member | None:
    """guild.get_member(id) → 見つからなければ guild.fetch_member(id)。
    NotFound / Forbidden / HTTPException → None。"""
```

---

## `src/bot/app.py`

```python
@dataclass(frozen=True, slots=True)
class BotRuntime:
    settings: Settings
    db: Database

def get_runtime(bot: commands.Bot) -> BotRuntime:
    """bot.runtime を BotRuntime として返す。未設定なら RuntimeError。"""
    runtime = getattr(bot, "runtime", None)
    if not isinstance(runtime, BotRuntime):
        raise RuntimeError("Bot runtime is not configured.")
    return runtime

class CTFBot(commands.Bot):
    def __init__(self, runtime: BotRuntime) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.runtime = runtime
        self._has_announced_ready = False
        self._shutdown_requested_by_sigint = False

    async def setup_hook(self) -> None:
        await load_cogs(self)
        synced = await self.tree.sync()
        logger.info("Synced %s command(s)", len(synced))

    async def on_ready(self) -> None:
        if self.user is None:
            return
        logger.info("%s has connected to Discord!", self.user)
        if not self._has_announced_ready:
            now = datetime.datetime.now(self.runtime.settings.tzinfo)
            await self._send_status(
                f"🟢 ctfbot connected at {now:%Y-%m-%d %H:%M:%S %Z}"
            )
            self._has_announced_ready = True

    async def close(self) -> None:
        if self._shutdown_requested_by_sigint and not self.is_closed():
            now = datetime.datetime.now(self.runtime.settings.tzinfo)
            await self._send_status(
                f"🔴 ctfbot disconnecting at {now:%Y-%m-%d %H:%M:%S %Z}"
            )
        await super().close()

    def mark_shutdown_requested(self) -> None:
        self._shutdown_requested_by_sigint = True

    async def _send_status(self, content: str) -> None:
        ch = await resolve_messageable(self, self.runtime.settings.bot_status_channel_id)
        if ch is not None:
            await send_safely(ch, content)

def create_bot(settings: Settings | None = None) -> CTFBot:
    loaded = settings or load_settings()
    configure_logging(loaded.log_level)
    db = Database(loaded.database_path)
    runtime = BotRuntime(settings=loaded, db=db)
    bot = CTFBot(runtime)

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, discord.app_commands.CommandOnCooldown):
            await send_interaction(interaction, "コマンドはクールダウン中です。")
            return
        if isinstance(error, discord.app_commands.MissingPermissions):
            await send_interaction(interaction, "このコマンドを実行する権限がありません。")
            return
        name = interaction.command.name if interaction.command else "<unknown>"
        logger.error("Unhandled error in /%s: %s", name, error)
        await send_interaction(interaction, "コマンド実行中にエラーが発生しました。")

    return bot

def run_bot(bot: CTFBot) -> None:
    previous = signal.getsignal(signal.SIGINT)

    def handle_sigint(signum: int, frame: FrameType | None) -> None:
        bot.mark_shutdown_requested()
        if previous is signal.SIG_IGN:
            return
        if previous is not signal.SIG_DFL:
            cast(Callable, previous)(signum, frame)
            return
        signal.default_int_handler(signum, frame)

    signal.signal(signal.SIGINT, handle_sigint)
    try:
        bot.run(bot.runtime.settings.discord_token, log_handler=None)
    finally:
        signal.signal(signal.SIGINT, previous)
```

---

## `src/bot/cogs_loader.py`

```python
DEFAULT_EXTENSIONS = (
    "bot.features.utility",
    "bot.features.times",
    "bot.features.alpacahack",
    "bot.features.ctf_team.cog",
    "bot.features.ctftime",
)

async def load_cogs(bot: commands.Bot) -> None:
    for ext in DEFAULT_EXTENSIONS:
        try:
            await bot.load_extension(ext)
        except Exception as exc:
            raise RuntimeError(f"Failed to load extension: {ext}") from exc
```

各 extension module は末尾に以下の setup 関数を定義する:

```python
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TheCogClass(bot))
```

---

## features/ctf_team/models.py

```python
class CampaignStatus(Enum):
    ACTIVE = "active"
    CLOSED = "closed"

@dataclass(frozen=True, slots=True)
class Campaign:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    role_id: int
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
    status: CampaignStatus
    created_by: int
    created_at_unix: int
    start_notified_at_unix: int | None = None
    closed_at_unix: int | None = None
    archive_at_unix: int | None = None
    archived_at_unix: int | None = None
    discussion_channel_id: int | None = None
    voice_channel_id: int | None = None

@dataclass(frozen=True, slots=True)
class CampaignDraft:
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
```

フィールド順は `db.py` の `_CAMPAIGN_COLUMNS` と一致させること。

---

## features/ctf_team/campaign.py

discord にも requests にも依存しない。`Database` とプリミティブ型のみ使う。

```python
MAX_ACTIVE_PER_USER = 5
MAX_CTF_NAME_LENGTH = 60
ARCHIVE_DELAY_DAYS = 30
INPUT_DATETIME_FORMAT = "%Y-%m-%d %H:%M"

def parse_datetime(raw: str, tz: datetime.tzinfo) -> datetime.datetime:
    """datetime.strptime(raw.strip(), INPUT_DATETIME_FORMAT).replace(tzinfo=tz)。
    ValueError → ServiceError("開始/終了日時の形式が不正です。YYYY-MM-DD HH:MM 形式で入力してください。")。"""

def to_unix(dt: datetime.datetime) -> int:
    """int(dt.timestamp())"""

def now_unix(tz: datetime.tzinfo) -> int:
    """int(datetime.datetime.now(tz).timestamp())"""

def validate_and_build_draft(
    db: Database,
    *,
    guild_id: int,
    created_by: int,
    ctf_name: str,
    start_at_raw: str,
    end_at_raw: str,
    timezone: datetime.tzinfo,
) -> CampaignDraft:
    """バリデーションして CampaignDraft を返す。失敗時 ServiceError。

    手順:
    1. " ".join(ctf_name.strip().split()) で空白正規化
    2. 空 → ServiceError("CTF名を入力してください。")
    3. len > 60 → ServiceError("CTF名が長すぎます。60文字以内で入力してください。")
    4. parse_datetime(start_at_raw, timezone)
    5. end_at_raw.strip() が空でなければ parse_datetime → end_at <= start_at なら
       ServiceError("終了日時は開始日時より後にしてください。常設CTFの場合は終了日時を空欄にしてください。")
    6. db.count_active_campaigns_by_creator(guild_id, created_by) >= 5 →
       ServiceError("同時に作成できる active 募集数の上限に達しています。(上限: 5)")
    7. db.has_active_campaign_with_name(guild_id, normalized_name) →
       ServiceError("同名の active 募集が既に存在します。別名を使うか既存募集を close してください。")
    8. CampaignDraft を返す
    """

def calculate_close(tz: datetime.tzinfo) -> tuple[int, int]:
    """現在時刻の closed_at_unix と archive_at_unix (= closed_at + 30日) を返す。"""

def is_expired(campaign: Campaign, tz: datetime.tzinfo) -> bool:
    """end_at_unix is not None and end_at_unix <= now_unix(tz)"""

def is_started(campaign: Campaign, tz: datetime.tzinfo) -> bool:
    """start_at_unix <= now_unix(tz)"""
```

---

## features/ctf_team/discord_ops.py

Discord オブジェクトを受け取る async 関数群。DB は触らない。

```python
MAX_CHANNEL_NAME_LENGTH = 100
CLOSED_HEADER = "🔒 **この募集は終了しました。**"
MENTION_CHUNK_SIZE = 1700  # Discord 2000文字制限にマージンを持たせた分割サイズ
```

```python
def normalize_channel_name(ctf_name: str) -> str:
    """lowercase → スペースを '-' に → [^a-z0-9\-] を除去 → 連続 '-' を 1 つに →
    先頭末尾の '-' を除去 → MAX_CHANNEL_NAME_LENGTH で切る。"""

def pick_unique_channel_name(category: discord.CategoryChannel, base: str) -> str:
    """category.channels の名前一覧と比較。被る場合 base-2, base-3 ... を試す。"""

async def create_discussion_channel(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    ctf_name: str,
    role: discord.Role,
    creator: discord.Member | None,
    bot_member: discord.Member | None,
) -> discord.TextChannel:
    """Permission overwrites:
    - guild.default_role: view_channel=False
    - role: view_channel=True, send_messages=True, read_message_history=True
    - creator（非 None 時）: 同上
    - bot_member（非 None 時）: 同上 + manage_channels=True
    チャンネル名は normalize_channel_name + pick_unique_channel_name。"""

async def create_voice_channel(
    guild: discord.Guild,
    category: discord.CategoryChannel,
    ctf_name: str,
    role: discord.Role,
    creator: discord.Member | None,
    bot_member: discord.Member | None,
) -> discord.VoiceChannel:
    """チャンネル名: normalize_channel_name(ctf_name) + "-voice"。
    Permission overwrites:
    - guild.default_role: view_channel=False
    - role: view_channel=True, connect=True, speak=True, stream=True
    - creator（非 None 時）: 同上
    - bot_member（非 None 時）: 同上"""

async def archive_discussion_channel(
    discussion: discord.TextChannel,
    archive_category: discord.CategoryChannel,
    role: discord.Role | None,
    bot_member: discord.Member | None,
) -> bool:
    """手順:
    1. bot_member の overwrite に manage_channels=True を設定
    2. discussion.edit(category=archive_category) で移動
    3. guild.default_role を view_channel=True, send_messages=False,
       add_reactions=False, create_public_threads=False, create_private_threads=False,
       read_message_history=True に変更
    4. role が非 None なら role の overwrite を削除
    5. "📦 このチャンネルは archive カテゴリに移動されました。" を投稿
    戻り値: 成功=True。
    NotFound（チャンネル消失）→ True（正常扱い）。Forbidden → False。"""

async def delete_voice_channel(
    bot: commands.Bot,
    guild: discord.Guild,
    channel_id: int | None,
) -> bool:
    """channel_id が None or 0 → True。
    guild.get_channel → 見つからなければ bot.fetch_channel。
    チャンネル不在 → True。削除失敗 → False。"""

async def cleanup_resources(
    *,
    message: discord.Message | None = None,
    role: discord.Role | None = None,
    discussion: discord.TextChannel | None = None,
    voice: discord.VoiceChannel | None = None,
) -> None:
    """作成途中で失敗した場合のロールバック。
    削除順序: message → voice → discussion → role。
    個別の削除失敗はログして続行。"""

async def mark_message_closed(
    channel: discord.TextChannel,
    message_id: int,
) -> bool:
    """channel.fetch_message(message_id) でメッセージ取得。
    content が CLOSED_HEADER で始まっていれば True（skip）。
    CLOSED_HEADER + "\n\n" + 既存 content で edit。
    成功 → True。失敗 → False。"""

async def send_start_announcement(
    channel: discord.TextChannel,
    campaign_name: str,
    role: discord.Role,
) -> tuple[int, bool]:
    """"🚀 **{campaign_name}** が開始しました！" を投稿。
    role.members からメンバー mention 一覧を構築。
    MENTION_CHUNK_SIZE ごとに分割して複数メッセージで送信。
    戻り値: (member_count, all_sent_successfully)。"""

async def send_close_snapshot(
    channel: discord.TextChannel,
    campaign_name: str,
    role: discord.Role,
) -> tuple[int, bool]:
    """"🔒 **{campaign_name}** の募集が終了しました。" を投稿。
    "参加メンバー ({count}人):" + メンバー mention 一覧。
    MENTION_CHUNK_SIZE ごとに分割。
    戻り値: (member_count, success)。"""

async def send_join_announcement(
    channel: discord.TextChannel,
    member: discord.Member,
    campaign_name: str,
) -> None:
    """"🙋 {member.mention} が **{campaign_name}** に参加しました。" を投稿。"""

def build_recruitment_message(
    draft: CampaignDraft,
    role: discord.Role,
    discussion_channel: discord.TextChannel,
) -> str:
    """以下の形式でテキストを組み立てる:

    📣 **{draft.ctf_name}** 参加者募集

    🕐 開始: <t:{start_at_unix}:f> (<t:{start_at_unix}:R>)
    🏁 終了: <t:{end_at_unix}:f> (<t:{end_at_unix}:R>)   ← end_at_unix が None なら "常設"
    💬 CTFチャンネル: {discussion_channel.mention}
    👥 ロール: {role.mention}

    ✅ リアクションを付けると {role.mention} ロールを付与します。
    """
```

---

## features/ctf_team/cog.py

```python
REACTION_EMOJI = "✅"
ROLE_ANNOUNCE_CHANNEL_NAME = "role"

ROLE_COLOR_SUGGESTIONS = (
    ("🟥 Red", "#ef4444"), ("🟧 Orange", "#f97316"), ("🟨 Yellow", "#eab308"),
    ("🟩 Green", "#22c55e"), ("🟦 Blue", "#3b82f6"), ("🟪 Purple", "#a855f7"),
    ("🟫 Brown", "#92400e"), ("⬜ White", "#f3f4f6"), ("⬛ Gray", "#6b7280"),
)
```

### CTFTeamCreateModal

```python
class CTFTeamCreateModal(discord.ui.Modal, title="CTF募集作成"):
    start_at = discord.ui.TextInput(
        label="開始日時 (YYYY-MM-DD HH:MM)",
        placeholder="2025-01-15 21:00",
        required=True,
        max_length=16,
    )
    end_at = discord.ui.TextInput(
        label="終了日時 (空欄で常設)",
        placeholder="2025-01-17 21:00",
        required=False,
        max_length=16,
    )

    def __init__(self, cog: CTFTeamCampaigns, ctf_name: str, role_color: discord.Colour) -> None:
        super().__init__()
        self.cog = cog
        self.ctf_name = ctf_name
        self.role_color = role_color

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_create_submit(
            interaction, self.ctf_name, self.role_color,
            self.start_at.value, self.end_at.value,
        )
```

### CTFTeamCampaigns

```python
class CTFTeamCampaigns(commands.GroupCog, group_name="ctfteam"):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        rt = get_runtime(bot)
        self.bot = bot
        self.settings = rt.settings
        self.db = rt.db
        self.start_due_campaigns.start()
        self.close_expired_campaigns.start()
        self.archive_closed_campaigns.start()

    def cog_unload(self) -> None:
        self.start_due_campaigns.cancel()
        self.close_expired_campaigns.cancel()
        self.archive_closed_campaigns.cancel()
```

### `/ctfteam open ctf_name [role_color]`

```python
@app_commands.command(name="open", description="CTF参加者の募集を作成します。")
@app_commands.describe(
    ctf_name="CTF名",
    role_color="ロールの色 (例: #3b82f6)",
)
@app_commands.choices(role_color=[
    app_commands.Choice(name=name, value=hex_val)
    for name, hex_val in ROLE_COLOR_SUGGESTIONS
])
async def open_campaign(self, interaction, ctf_name: str, role_color: str = "#3b82f6"):
    # role_color: '#' を strip して int(hex, 16) → discord.Colour。ValueError → エラー応答。
    modal = CTFTeamCreateModal(self, ctf_name, colour)
    await interaction.response.send_modal(modal)
```

### handle_create_submit（Modal の on_submit から呼ばれる）

```python
async def handle_create_submit(
    self, interaction, ctf_name, role_color, start_at_raw, end_at_raw,
):
    await interaction.response.defer(ephemeral=True)

    # 1. validation（asyncio.to_thread で実行）
    try:
        draft = await asyncio.to_thread(
            campaign.validate_and_build_draft,
            self.db,
            guild_id=interaction.guild_id,
            created_by=interaction.user.id,
            ctf_name=ctf_name,
            start_at_raw=start_at_raw,
            end_at_raw=end_at_raw,
            timezone=self.settings.tzinfo,
        )
    except ServiceError as exc:
        await send_interaction(interaction, str(exc))
        return

    guild = interaction.guild
    role = None
    discussion = None
    voice = None
    recruit_msg = None

    try:
        # 2. #role チャンネルを探す（category_id 配下で名前が "role" のテキストチャンネル）
        category = guild.get_channel(self.settings.ctf_team_category_id)
        # category が None or CategoryChannel でない → エラー
        role_channel = discord.utils.get(category.text_channels, name=ROLE_ANNOUNCE_CHANNEL_NAME)
        # role_channel が None → エラー

        # 3. role 作成
        role = await guild.create_role(name=draft.ctf_name, colour=role_color, mentionable=True)

        # 4. discussion channel 作成
        discussion = await discord_ops.create_discussion_channel(
            guild, category, draft.ctf_name, role,
            guild.get_member(interaction.user.id), guild.me,
        )

        # 5. voice channel 作成
        voice = await discord_ops.create_voice_channel(
            guild, category, draft.ctf_name, role,
            guild.get_member(interaction.user.id), guild.me,
        )

        # 6. 募集メッセージ送信 + ✅ リアクション
        text = discord_ops.build_recruitment_message(draft, role, discussion)
        recruit_msg = await role_channel.send(text)
        await recruit_msg.add_reaction(REACTION_EMOJI)

        # 7. DB に保存（asyncio.to_thread）
        try:
            created = await asyncio.to_thread(
                self.db.create_campaign,
                guild_id=guild.id, channel_id=role_channel.id,
                message_id=recruit_msg.id, role_id=role.id,
                discussion_channel_id=discussion.id,
                voice_channel_id=voice.id,
                ctf_name=draft.ctf_name,
                start_at_unix=draft.start_at_unix,
                end_at_unix=draft.end_at_unix,
                created_by=interaction.user.id,
                created_at_unix=campaign.now_unix(self.settings.tzinfo),
            )
        except ConflictError:
            await discord_ops.cleanup_resources(
                message=recruit_msg, role=role, discussion=discussion, voice=voice,
            )
            await send_interaction(interaction, "同名の募集が既に作成されました。")
            return

        # 8. 作成者に role 付与
        member = guild.get_member(interaction.user.id)
        if member and role not in member.roles:
            await member.add_roles(role)

        # 9. 開始時刻を過ぎていれば即座に開始通知
        if campaign.is_started(created, self.settings.tzinfo):
            if discussion and created.start_notified_at_unix is None:
                await discord_ops.send_start_announcement(discussion, created.ctf_name, role)
                await asyncio.to_thread(
                    self.db.mark_started, created.id, campaign.now_unix(self.settings.tzinfo),
                )

        await send_interaction(interaction, f"**{draft.ctf_name}** の募集を作成しました。")
        await log_audit(self.bot, interaction, command_name="ctfteam open",
                        details=[f"CTF名: {draft.ctf_name}"])

    except Exception:
        logger.exception("Failed to create campaign: %s", ctf_name)
        await discord_ops.cleanup_resources(
            message=recruit_msg, role=role, discussion=discussion, voice=voice,
        )
        await send_interaction(interaction, "募集の作成中にエラーが発生しました。")
```

### `/ctfteam list [status]`

```python
@app_commands.command(name="list", description="CTF募集の一覧を表示します。")
@app_commands.describe(status="表示するステータス")
@app_commands.choices(status=[
    app_commands.Choice(name="募集中", value="active"),
    app_commands.Choice(name="終了", value="closed"),
    app_commands.Choice(name="すべて", value="all"),
])
async def list_campaigns(self, interaction, status: str = "active"):
    filter_status = None if status == "all" else status
    campaigns = await asyncio.to_thread(
        self.db.list_campaigns, interaction.guild_id, filter_status,
    )
    # Embed 構築（後述）
    await interaction.response.send_message(embed=embed, ephemeral=True)
```

Embed 形式（description に全件をテキストで入れる）:

```
タイトル: CTF募集一覧 (募集中 / 終了 / すべて)
description:
  {N}件を表示しています。

  **1. {ctf_name}**
  状態: 募集中 / 終了
  開始: <t:X:f> (<t:X:R>)
  終了: <t:Y:f> (<t:Y:R>) or 常設
  募集: [メッセージへ移動](https://discord.com/channels/{guild}/{channel}/{message})
  議論: <#{discussion_channel_id}> or -
  VC: <#{voice_channel_id}> or -
  ロール: <@&{role_id}>
  作成者: <@{created_by}>
  archive予定: <t:Z:f> (<t:Z:R>)  ← closed の場合のみ

  **2. {ctf_name}**
  ...
```

campaign が 0 件なら "該当する募集はありません。"。
description が 4096 文字を超える場合は表示件数を減らして "他 {remaining} 件は省略しています。" を追加。

### `/ctfteam close ctf_name`

```python
@app_commands.command(name="close", description="CTF募集を終了します。")
@app_commands.describe(ctf_name="終了するCTF名")
async def close_campaign_cmd(self, interaction, ctf_name: str):
    await interaction.response.defer(ephemeral=True)
    c = await asyncio.to_thread(
        self.db.find_campaign_by_name,
        guild_id=interaction.guild_id, ctf_name=ctf_name.strip(),
        status=CampaignStatus.ACTIVE,
    )
    if c is None:
        await send_interaction(interaction, f"active 募集 '{ctf_name}' が見つかりません。")
        return

    # 権限チェック: 作成者 or interaction.user に manage_guild 権限
    if c.created_by != interaction.user.id:
        if not interaction.user.guild_permissions.manage_guild:
            await send_interaction(interaction, "この募集を終了する権限がありません。")
            return

    closed_at, archive_at = campaign.calculate_close(self.settings.tzinfo)
    await asyncio.to_thread(self.db.close_campaign, c.id, closed_at, archive_at)

    guild = interaction.guild
    # discussion channel に close snapshot
    if c.discussion_channel_id:
        disc_ch = guild.get_channel(c.discussion_channel_id)
        if disc_ch:
            role = guild.get_role(c.role_id)
            if role:
                await discord_ops.send_close_snapshot(disc_ch, c.ctf_name, role)

    # 募集メッセージに CLOSED_HEADER 追加
    recruit_ch = guild.get_channel(c.channel_id)
    if recruit_ch:
        await discord_ops.mark_message_closed(recruit_ch, c.message_id)

    # voice channel 削除
    await discord_ops.delete_voice_channel(self.bot, guild, c.voice_channel_id)

    archive_ts = format_timestamp_with_relative(archive_at)
    await send_interaction(interaction,
        f"**{c.ctf_name}** を終了しました。archive 予定: {archive_ts}")
    await log_audit(self.bot, interaction, command_name="ctfteam close",
                    details=[f"CTF名: {c.ctf_name}"])
```

### `/ctfteam archive ctf_name`

```python
@app_commands.command(name="archive", description="終了済み募集を手動でarchiveします。")
@app_commands.describe(ctf_name="archiveするCTF名")
async def archive_campaign_cmd(self, interaction, ctf_name: str):
    await interaction.response.defer(ephemeral=True)

    # まず closed + 未 archive で検索
    c = await asyncio.to_thread(
        self.db.find_campaign_by_name,
        guild_id=interaction.guild_id, ctf_name=ctf_name.strip(),
        status=CampaignStatus.CLOSED, archived=False,
    )
    if c is None:
        # active で存在するか確認 → 「先に /ctfteam close してください」
        active = await asyncio.to_thread(
            self.db.find_campaign_by_name,
            guild_id=interaction.guild_id, ctf_name=ctf_name.strip(),
            status=CampaignStatus.ACTIVE,
        )
        if active:
            await send_interaction(interaction,
                f"'{ctf_name}' は募集中です。先に `/ctfteam close` で終了してください。")
            return

        # archived 済みか確認
        archived = await asyncio.to_thread(
            self.db.find_campaign_by_name,
            guild_id=interaction.guild_id, ctf_name=ctf_name.strip(),
            status=CampaignStatus.CLOSED, archived=True,
        )
        if archived:
            await send_interaction(interaction, f"'{ctf_name}' は既に archive 済みです。")
            return

        await send_interaction(interaction, f"募集 '{ctf_name}' が見つかりません。")
        return

    # 権限チェック: 作成者 or manage_guild
    if c.created_by != interaction.user.id:
        if not interaction.user.guild_permissions.manage_guild:
            await send_interaction(interaction, "この募集を archive する権限がありません。")
            return

    guild = interaction.guild
    archive_category = guild.get_channel(self.settings.ctf_team_archive_category_id)

    # discussion channel を archive
    if c.discussion_channel_id:
        disc_ch = guild.get_channel(c.discussion_channel_id)
        if disc_ch and archive_category:
            role = guild.get_role(c.role_id)
            await discord_ops.archive_discussion_channel(
                disc_ch, archive_category, role, guild.me,
            )

    # voice channel 削除
    await discord_ops.delete_voice_channel(self.bot, guild, c.voice_channel_id)

    # role 削除
    role = guild.get_role(c.role_id)
    if role:
        try:
            await role.delete()
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Failed to delete role %s", c.role_id)

    # DB 更新
    await asyncio.to_thread(
        self.db.mark_archived, c.id, campaign.now_unix(self.settings.tzinfo),
    )

    await send_interaction(interaction, f"**{c.ctf_name}** を archive しました。")
    await log_audit(self.bot, interaction, command_name="ctfteam archive",
                    details=[f"CTF名: {c.ctf_name}"])
```

### Reaction Handler

```python
@commands.Cog.listener()
async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
    if str(payload.emoji) != REACTION_EMOJI:
        return
    if payload.user_id == self.bot.user.id:
        return

    c = await asyncio.to_thread(
        self.db.find_active_campaign_by_message,
        guild_id=payload.guild_id,
        channel_id=payload.channel_id,
        message_id=payload.message_id,
    )
    if c is None:
        return

    guild = self.bot.get_guild(payload.guild_id)
    if guild is None:
        return

    # 期限切れチェック → auto-close（close コマンドと同じフロー。interaction がないので audit 省略）
    if campaign.is_expired(c, self.settings.tzinfo):
        closed_at, archive_at = campaign.calculate_close(self.settings.tzinfo)
        was_closed = await asyncio.to_thread(self.db.close_campaign, c.id, closed_at, archive_at)
        if was_closed:
            if c.discussion_channel_id:
                disc_ch = guild.get_channel(c.discussion_channel_id)
                role = guild.get_role(c.role_id)
                if disc_ch and role:
                    await discord_ops.send_close_snapshot(disc_ch, c.ctf_name, role)
            recruit_ch = guild.get_channel(c.channel_id)
            if recruit_ch:
                await discord_ops.mark_message_closed(recruit_ch, c.message_id)
            await discord_ops.delete_voice_channel(self.bot, guild, c.voice_channel_id)
        return

    role = guild.get_role(c.role_id)
    if role is None:
        return

    member = await fetch_member(guild, payload.user_id)
    if member is None:
        return

    if role not in member.roles:
        try:
            await member.add_roles(role)
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Failed to add role to member %s", payload.user_id)
            return

        # discussion channel に参加通知
        if c.discussion_channel_id:
            disc_ch = guild.get_channel(c.discussion_channel_id)
            if disc_ch:
                await discord_ops.send_join_announcement(disc_ch, member, c.ctf_name)
```

`on_raw_reaction_remove` は実装しない（role 除去は archive まで行わない）。

### Background Tasks

3 つとも同じパターン:

```python
@tasks.loop(minutes=1)
async def start_due_campaigns(self) -> None:
    try:
        now = campaign.now_unix(self.settings.tzinfo)
        due = await asyncio.to_thread(self.db.list_due_starts, now)
        for c in due:
            guild = self.bot.get_guild(c.guild_id)
            if guild is None:
                continue
            if c.discussion_channel_id:
                disc_ch = guild.get_channel(c.discussion_channel_id)
                role = guild.get_role(c.role_id)
                if disc_ch and role:
                    await discord_ops.send_start_announcement(disc_ch, c.ctf_name, role)
            await asyncio.to_thread(self.db.mark_started, c.id, campaign.now_unix(self.settings.tzinfo))
    except Exception:
        logger.exception("Error in start_due_campaigns")

@start_due_campaigns.before_loop
async def before_start_due(self) -> None:
    await self.bot.wait_until_ready()
```

`close_expired_campaigns`: `list_due_campaigns(now)` → 各 campaign に close フロー（close コマンドと同じ DB 更新 + Discord 操作。interaction がないので audit ログ省略）。

`archive_closed_campaigns`: `list_due_archives(now)` → 各 campaign に archive フロー（archive コマンドと同じ DB 更新 + Discord 操作。interaction がないので audit ログ省略）。

### setup 関数

```python
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CTFTeamCampaigns(bot))
```

---

## features/ctftime.py

### データ型

```python
@dataclass(frozen=True, slots=True)
class CTFEvent:
    title: str
    start: datetime.datetime
    finish: datetime.datetime
    ctftime_url: str
```

### CTFTimeClient

```python
class CTFTimeClient:
    def __init__(self, *, timezone: datetime.tzinfo, user_agent: str,
                 request_timeout: int = 10, max_retries: int = 3,
                 retry_backoff: float = 1.5) -> None:
        self._timezone = timezone
        self._user_agent = user_agent
        self._timeout = request_timeout
        self._max_retries = max_retries
        self._backoff = retry_backoff

    def fetch_events(self, days: int, limit: int) -> list[CTFEvent]:
        """GET https://ctftime.org/api/v1/events/?limit={limit}&start={start_unix}&finish={finish_unix}
        Headers: User-Agent={self._user_agent}
        start = now, finish = now + days 日。

        リトライ: max_retries 回。間隔 = backoff * attempt 秒（time.sleep）。
        全失敗 → ExternalAPIError。

        JSON レスポンスの各要素から:
        - title: str
        - start: ISO 8601 文字列 → datetime.fromisoformat
        - finish: ISO 8601 文字列 → datetime.fromisoformat
        - ctftime_url: str（なければ url フィールド）
        """
```

### CTFTimeNotifications (Cog)

```python
class CTFTimeNotifications(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        rt = get_runtime(bot)
        self.bot = bot
        self.settings = rt.settings
        self.client = CTFTimeClient(
            timezone=self.settings.tzinfo,
            user_agent=self.settings.ctftime_user_agent,
        )
        self.weekly_ctf_notification.start()

    def cog_unload(self) -> None:
        self.weekly_ctf_notification.cancel()

    @tasks.loop(time=[])  # before_loop で change_interval
    async def weekly_ctf_notification(self) -> None:
        """settings.ctftime_notification_time に毎日起動。
        datetime.datetime.now(settings.tzinfo).weekday() != 0（月曜以外）なら即 return。

        月曜なら:
        events = await asyncio.to_thread(
            self.client.fetch_events, self.settings.ctftime_window_days, self.settings.ctftime_event_limit,
        )
        Embed を構築して settings.ctftime_channel_id に送信。
        channel_id <= 0 なら何もしない。"""

    @weekly_ctf_notification.before_loop
    async def before_weekly(self) -> None:
        await self.bot.wait_until_ready()
        self.weekly_ctf_notification.change_interval(time=self.settings.ctftime_notification_time)

    @app_commands.command(name="ctftime", description="CTFtimeの予定を手動で取得します。")
    async def manual_ctf_check(self, interaction: discord.Interaction) -> None:
        """interaction.response.defer() → fetch_events → Embed → interaction の channel に送信。
        ExternalAPIError → "CTFtime からの取得に失敗しました。""""
```

Embed 形式:
- タイトル: "📅 今後{window_days}日間のCTFイベント"
- 各イベントは description 内に:
  ```
  **{title}**
  🕐 <t:{start_unix}:f> 〜 <t:{finish_unix}:f>
  🔗 [CTFtime]({ctftime_url})
  ```
- 0 件なら "予定されているイベントはありません。"
- description 4096 文字上限で打ち切り

```python
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CTFTimeNotifications(bot))
```

---

## features/alpacahack.py

### データ型

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

### 純粋ロジック

```python
def get_week_range(reference_date: datetime.date) -> tuple[datetime.date, datetime.date]:
    """月曜始まりの週。
    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)"""

def select_weekly_solves(
    records: Sequence[SolveRecord], *, week_start: datetime.date, week_end: datetime.date,
) -> list[SolveRecord]:
    """solved_at.date() が week_start <= d <= week_end の records をフィルタ。
    (challenge_url or challenge_name) で重複除去。solved_at 昇順でソート。"""
```

### AlpacaHackClient

```python
class AlpacaHackClient:
    def __init__(self, *, timezone: datetime.tzinfo, request_timeout: int = 10) -> None:
        self._timezone = timezone
        self._timeout = request_timeout

    def fetch_solve_records(self, username: str) -> list[SolveRecord]:
        """GET https://alpacahack.com/users/{username}
        BeautifulSoup で HTML をパース。

        "SOLVED CHALLENGES" セクションの table を探す:
        - 各 tr の td[0] → challenge name（a タグの text）、href（あれば）
        - 各 tr の td[2] → solved_at（time タグの aria-label 属性）
        - aria-label のパース: r"(\\d{4}-\\d{2}-\\d{2})[ T](\\d{2}:\\d{2}(?::\\d{2})?)"
          → UTC として解釈 → self._timezone に変換

        RequestException → ExternalAPIError。"""
```

### collect_weekly_summary（同期関数）

```python
def collect_weekly_summary(
    db: Database,
    client: AlpacaHackClient,
    *,
    timezone: datetime.tzinfo,
    reference_date: datetime.date | None = None,
    request_interval: float = 0.2,
) -> WeeklySolveSummary:
    """同期関数。cog からは asyncio.to_thread で呼ぶ。

    1. db.list_alpacahack_users() で全ユーザー取得
    2. 各ユーザーについて:
       a. client.fetch_solve_records(username)
       b. select_weekly_solves でフィルタ
       c. ExternalAPIError → failed_users に追加
       d. ユーザー間に time.sleep(request_interval)
    3. WeeklySolveSummary を返す"""
```

### Alpacahack (GroupCog)

```python
class Alpacahack(commands.GroupCog, group_name="alpaca"):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        rt = get_runtime(bot)
        self.bot = bot
        self.settings = rt.settings
        self.db = rt.db
        self.client = AlpacaHackClient(timezone=self.settings.tzinfo)
        self.weekly_solve_report.start()

    def cog_unload(self) -> None:
        self.weekly_solve_report.cancel()

    @tasks.loop(time=[])  # before_loop で change_interval
    async def weekly_solve_report(self) -> None:
        """settings.alpacahack_solve_time に毎日起動。
        日曜 (weekday()==6) 以外は return。
        collect_weekly_summary を asyncio.to_thread で呼ぶ。
        Embed を構築して settings.alpacahack_channel_id に送信。
        channel_id <= 0 なら何もしない。"""

    @weekly_solve_report.before_loop
    async def before_weekly_solve(self) -> None:
        await self.bot.wait_until_ready()
        self.weekly_solve_report.change_interval(time=self.settings.alpacahack_solve_time)

    @app_commands.command(name="add", description="AlpacaHackユーザーを登録します。")
    @app_commands.describe(username="AlpacaHackのユーザー名")
    async def add_user(self, interaction: discord.Interaction, username: str) -> None:
        name = username.strip()
        if not name:
            await send_interaction(interaction, "ユーザー名が空です。")
            return
        created = await asyncio.to_thread(self.db.add_alpacahack_user, name)
        if created:
            await send_interaction(interaction, f"`{name}` を登録しました。")
            await log_audit(self.bot, interaction, command_name="alpaca add",
                            details=[f"ユーザー名: {name}"])
        else:
            await send_interaction(interaction, f"`{name}` は既に登録されています。")

    @app_commands.command(name="del", description="AlpacaHackユーザーの登録を削除します。")
    @app_commands.describe(username="AlpacaHackのユーザー名")
    async def del_user(self, interaction: discord.Interaction, username: str) -> None:
        name = username.strip()
        if not name:
            await send_interaction(interaction, "ユーザー名が空です。")
            return
        deleted = await asyncio.to_thread(self.db.delete_alpacahack_user, name)
        if deleted:
            await send_interaction(interaction, f"`{name}` の登録を削除しました。")
            await log_audit(self.bot, interaction, command_name="alpaca del",
                            details=[f"ユーザー名: {name}"])
        else:
            await send_interaction(interaction, f"`{name}` は登録されていません。")

    @app_commands.command(name="list", description="登録済みAlpacaHackユーザー一覧を表示します。")
    async def list_users(self, interaction: discord.Interaction) -> None:
        users = await asyncio.to_thread(self.db.list_alpacahack_users)
        if not users:
            await send_interaction(interaction, "登録ユーザーはいません。")
            return
        lines = [f"- {u}" for u in users]
        await send_interaction(interaction, f"登録ユーザー ({len(users)}人):\n" + "\n".join(lines))

    @app_commands.command(name="solve", description="今週のsolve状況を表示します。")
    async def show_solves(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        summary = await asyncio.to_thread(
            collect_weekly_summary, self.db, self.client, timezone=self.settings.tzinfo,
        )
        # Embed 構築 → interaction.followup.send(embed=embed)
```

Embed 形式:
```
タイトル: 🦙 AlpacaHack 今週の solve
description: {week_start} 〜 {week_end}
{solved_count}人/{total_users}人, {total_solves} solves
（取得失敗 {len(failed_users)}人 ← 0人なら省略）

各ユーザー → Embed field:
name: {username} ({len(solves)} solves)
value:
- [{challenge_name}]({url})  ← url が None なら名前のみ
- ...
12 件まで。超過時は "... 他 {n} 件"。
field の value は 1024 文字まで。

failed_users が非空なら最後の field:
name: ⚠️ 取得失敗
value: user1, user2, ...
```

```python
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Alpacahack(bot))
```

---

## features/times.py

```python
class TimesChannels(commands.GroupCog, group_name="times"):
    CATEGORY_NAME = "times"

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(name="create", description="timesカテゴリにテキストチャンネルを作成します。")
    @app_commands.describe(names="作成するチャンネル名 (カンマ区切りで複数指定可)")
    async def create_times(self, interaction: discord.Interaction, names: str) -> None:
        """パース: re.split(r'[,、\n]+', names) → 各要素を strip → 空文字除去
        → normalize（lowercase, [^a-z0-9\-] を '-' に, 連続 '-' を 1 つに, 先頭末尾 '-' 除去）。

        guild.categories から名前が self.CATEGORY_NAME のカテゴリを検索。
        なければ → "times カテゴリが見つかりません。"

        各名前について:
        - カテゴリ内に同名チャンネルが既存 → スキップ
        - なければ作成

        結果:
        - 作成: "✅ #name1, #name2 を作成しました。"
        - スキップ: "⏭️ #name3 は既に存在します。"
        - 両方あれば両方表示"""

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TimesChannels(bot))
```

---

## features/utility.py

```python
class UtilityCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="利用可能なコマンド一覧を表示します。")
    async def help_command(self, interaction: discord.Interaction) -> None:
        """bot.tree.get_commands() で全コマンド取得。
        Group コマンドは展開して /group subcommand 形式で列挙。
        各コマンド: "/{name} — {description}"
        ephemeral で応答。"""

    @app_commands.command(name="perms", description="このサーバー/チャンネルでのbot権限を表示します。")
    @app_commands.describe(channel="確認対象チャンネル (省略時は実行チャンネル)")
    async def perms_check(
        self, interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """対象チャンネル = channel or interaction.channel。
        guild.me.guild_permissions と channel.permissions_for(guild.me) を取得。

        チェックする権限:
        Guild: manage_roles
        Channel: view_channel, send_messages, send_messages_in_threads,
                 read_message_history, add_reactions, manage_channels

        各権限を ✅ / ❌ で表示。ephemeral。"""

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCommands(bot))
```

---

## テスト

全テストは `unittest` を使う。pytest は使わない。

### test_architecture.py

AST で import ルールを検証:
1. `campaign.py` が `discord` を import していないこと
2. `db.py` が `discord` を import していないこと
3. `discord_ops.py` が `bot.db` を import していないこと
4. feature 間の相互 import がないこと（`ctftime.py` が `ctf_team` や `alpacahack` を import していない、等）

### test_config.py

- 全必須項目あり → Settings 正常構築
- `DISCORD_TOKEN` 欠落 → `ConfigurationError`
- `CTF_TEAM_CATEGORY_ID` = 0 → `ConfigurationError`
- 不正な `TIMEZONE` → `ConfigurationError`
- `DATABASE_PATH` の親ディレクトリ不在 → `ConfigurationError`
- 各デフォルト値の確認
- `_read_clock_time` の正常・異常パターン

### test_db.py

テスト用 `Database` は `tempfile.mktemp()` で一時パスを生成して使う。

- schema 初期化: テーブルと index が存在すること
- `user_version` が `CURRENT_SCHEMA_VERSION` であること
- 再初期化で version チェックが通ること
- version 不一致で `RepositoryError`
- `add_alpacahack_user`: 新規→True、重複→False
- `delete_alpacahack_user`: 存在→True、不在→False
- `list_alpacahack_users`: 名前順
- `create_campaign`: 正常作成
- `create_campaign` 同名 active → `ConflictError`
- `find_active_campaign_by_message`: 存在/不在
- `find_campaign_by_name`: status + archived フィルタ
- `close_campaign`: status 変更、closed_at/archive_at 設定
- `mark_started`: start_notified_at_unix 設定、二重実行で False
- `mark_archived`: archived_at_unix 設定
- `list_due_campaigns`, `list_due_starts`, `list_due_archives`: 条件一致/不一致

### test_campaign.py

テスト用 `Database` は `tempfile.mktemp()` で一時パスを生成して使う。

- `validate_and_build_draft`: 正常入力 → `CampaignDraft` 返却
- 空 CTF 名 → `ServiceError`
- 61 文字 CTF 名 → `ServiceError`
- 不正日時 → `ServiceError`
- 終了 < 開始 → `ServiceError`
- active 上限 5 超過 → `ServiceError`（事前に 5 件作成）
- 同名 active → `ServiceError`
- `calculate_close`: `closed_at` と `archive_at` の差が 30 日
- `is_expired`: `end_at_unix` が過去 → True、未来 → False、None → False
- `is_started`: `start_at_unix` が過去 → True、未来 → False

### test_ctftime_client.py

`requests.get` をモックして検証。

- 正常 JSON → `CTFEvent` リスト変換
- ISO datetime（"Z" 付き、"+09:00" 付き）の正しいパース
- 1 回目失敗 → 2 回目成功（リトライ動作）。`time.sleep` もモックして実際に待たない。
- 全失敗 → `ExternalAPIError`

### test_alpacahack.py

- `get_week_range`: 月曜 → 当日〜日曜。日曜 → 前日の月曜〜当日。
- `select_weekly_solves`: 今週のみフィルタ、url ベースの重複除去
- HTML パース: `fetch_solve_records` に対して HTML 文字列をモック。SOLVED CHALLENGES テーブルからのレコード抽出。
- `collect_weekly_summary`: 2 ユーザー（1 成功 + 1 失敗）の混在集計

---

## .env.example

```env
# 必須
DISCORD_TOKEN=
CTF_TEAM_CATEGORY_ID=
CTF_TEAM_ARCHIVE_CATEGORY_ID=

# 任意（0 で無効）
BOT_CHANNEL_ID=0
BOT_STATUS_CHANNEL_ID=0
CTFTIME_CHANNEL_ID=0
ALPACAHACK_CHANNEL_ID=0

# デフォルトあり
TIMEZONE=Asia/Tokyo
LOG_LEVEL=INFO
DATABASE_PATH=ctfbot.db
ALPACAHACK_SOLVE_TIME=23:00
CTFTIME_NOTIFICATION_TIME=09:00
CTFTIME_WINDOW_DAYS=14
CTFTIME_EVENT_LIMIT=20
CTFTIME_USER_AGENT=ctfbot/2.0 (+discord)
```

---

## 実装順序

1. `pyproject.toml`, `src/main.py`, `src/bot/__init__.py`, `errors.py`, `log.py`
2. `config.py` + `tests/test_config.py`
3. `db.py` + `tests/test_db.py`
4. `helpers.py`
5. `app.py`, `cogs_loader.py`
6. `features/ctf_team/models.py`
7. `features/ctf_team/campaign.py` + `tests/test_campaign.py`
8. `features/ctf_team/discord_ops.py`
9. `features/ctf_team/cog.py` + `features/ctf_team/__init__.py`
10. `features/ctftime.py` + `tests/test_ctftime_client.py`
11. `features/alpacahack.py` + `tests/test_alpacahack.py`
12. `features/times.py`
13. `features/utility.py`
14. `features/__init__.py`
15. `tests/test_architecture.py`
16. `.env.example`

各ステップ後に実行:

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check
uv run python -m unittest discover -s tests -v
```
