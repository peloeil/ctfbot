# 実装指示: 設計レビュー指摘の修正 (2026-07-06)

## この文書について

`docs/design-review-2026-07-06.md`（設計レビュー）の指摘を修正するための実装指示。**この文書だけで実装を完了できる**ように書かれている。レビュー本文を読む必要はないが、背景を知りたい場合は参照してよい。

- 情報の優先順位: **この文書 > AGENTS.md > docs/**（AGENTS.md 記載のルール通り）
- **docs/（design.md, features/*.md）と AGENTS.md は既に「実装完了後の目標状態」に更新済み。** 現行コードとの食い違いは「これから実装する差分」であり、ドキュメントのバグではない。ドキュメントは変更しないこと
- 作業前に `uv sync --group dev` を実行すること
- コーディング規約・検証手順は AGENTS.md に従う。コメントは原則書かない

## 実装順序

タスク 1（runtime.py 新設）が他タスクの import 前提になるため最初に行う。それ以外は独立。

1. タスク 1: `bot/runtime.py` の新設と import 差し替え
2. タスク 2: DB スキーマ migration 機構
3. タスク 3: close フローの冪等化 ← **最重要（バグ修正）**
4. タスク 4: 週次通知の二重送信修正
5. タスク 5: `/times create` の作成上限
6. タスク 6: `Database.list_campaigns` の型統一
7. タスク 7: アーキテクチャテストの拡充
8. タスク 8: discord_ops 純粋関数のテスト追加

---

## タスク 1: `bot/runtime.py` の新設と import 差し替え

**対象**: `src/bot/runtime.py`（新規）, `src/bot/app.py`, `src/bot/helpers.py`, `src/bot/features/ctf_team/cog.py`, `src/bot/features/alpacahack.py`, `src/bot/features/ctftime.py`

**背景**: `BotRuntime` / `get_runtime` が `app.py` にあるため、feature がアプリ全体（CTFBot クラス・signal 処理）に依存している。また `helpers.py` は `app.py` を import すると循環になるため、`log_audit` が `getattr` チェーンで型を捨てて runtime にアクセスしている。

### 1-1. `src/bot/runtime.py` を新規作成

`app.py` にある `BotRuntime` と `get_runtime` を**そのまま**移動する:

```python
from dataclasses import dataclass

from discord.ext import commands

from bot.config import Settings
from bot.db import Database


@dataclass(frozen=True, slots=True)
class BotRuntime:
    settings: Settings
    db: Database


def get_runtime(bot: commands.Bot) -> BotRuntime:
    runtime = getattr(bot, "runtime", None)
    if not isinstance(runtime, BotRuntime):
        raise RuntimeError("Bot runtime is not configured.")
    return runtime
```

### 1-2. `app.py` から定義を削除し import に置き換え

`app.py` の `BotRuntime` dataclass と `get_runtime` 関数を削除し、`from bot.runtime import BotRuntime` を追加する（`create_bot` が `BotRuntime` を使うため）。`app.py` 内でしか使わなくなった import（`dataclass` 等）が残らないよう整理する。

### 1-3. feature の import を差し替え

`cog.py`, `alpacahack.py`, `ctftime.py` の `from bot.app import get_runtime` を `from bot.runtime import get_runtime` に変更する。変更後、これら 3 ファイルは `bot.app` を import しなくなる。

### 1-4. `helpers.py` の `log_audit` を型安全にする

現在の実装（`helpers.py:80-82` 付近）:

```python
runtime = getattr(bot, "runtime", None)
settings = getattr(runtime, "settings", None)
channel_id = getattr(settings, "bot_channel_id", 0)
```

これを次に置き換える:

```python
try:
    runtime = get_runtime(bot)
except RuntimeError:
    return
channel_id = runtime.settings.bot_channel_id
```

ファイル先頭に `from bot.runtime import get_runtime` を追加する。

**注意**: `helpers.py` → `runtime.py` → `db.py` という import 連鎖が生まれるが、これは docs/design.md の依存ルールで許可済み。`discord_ops.py` が **直接** `bot.db` を import しない制約（アーキテクチャテスト対象）は変わらず守られる。

### 受け入れ条件

- `src/bot/` 内に `from bot.app import get_runtime` が残っていない（`grep -rn "from bot.app import" src/` で `main.py` の `create_bot, run_bot` のみになる）
- 既存テストが全てパスする

---

## タスク 2: DB スキーマ migration 機構

**対象**: `src/bot/db.py`, `tests/test_db.py`

**背景**: 現在の `_ensure_schema` は `user_version` が `CURRENT_SCHEMA_VERSION` と一致しない DB を起動拒否するだけで、移行手段がない。「スキーマ変更時は version をインクリメント」という開発ルールに従うと、既存の本番 DB が起動不能になる。

### 2-1. `_MIGRATIONS` 定数を追加

`CURRENT_SCHEMA_VERSION = 1` の直後に追加する:

```python
_MIGRATIONS: dict[int, str] = {}
```

キーは移行元 version、値は「version N → N+1」へ移行する SQL スクリプト。現時点で version 1 が最新なので**空 dict でよい**。

### 2-2. `_ensure_schema` を書き換え

現在の実装を以下に置き換える:

```python
def _ensure_schema(self) -> None:
    with self._connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        table_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        if version == 0 and table_count > 0:
            raise RepositoryError("Unmanaged database schema.")
        if version > CURRENT_SCHEMA_VERSION:
            message = (
                f"Unsupported schema version: {version}; "
                f"expected {CURRENT_SCHEMA_VERSION}."
            )
            raise RepositoryError(message)
        if version == 0:
            conn.executescript(_SCHEMA_DDL)
            conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
            conn.commit()
            return
        while version < CURRENT_SCHEMA_VERSION:
            script = _MIGRATIONS.get(version)
            if script is None:
                raise RepositoryError(
                    f"No migration path from schema version {version}."
                )
            conn.executescript(script)
            version += 1
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
        conn.executescript(_SCHEMA_DDL)
        conn.commit()
```

挙動の整理（既存挙動は 4 つとも維持し、migration 適用だけが新規）:

| DB の状態 | 挙動 |
|---|---|
| `version == 0` かつテーブルなし | 新規初期化（既存挙動） |
| `version == 0` かつテーブルあり | `Unmanaged database schema.` で起動拒否（既存挙動） |
| `version == CURRENT` | 冪等 DDL を流して起動（既存挙動） |
| `version > CURRENT` | `Unsupported schema version` で起動拒否（既存挙動） |
| `0 < version < CURRENT` | `_MIGRATIONS` を version 順に適用（**新規**）。パスが無ければ `No migration path` で起動拒否 |

### 2-3. テスト追加（`tests/test_db.py`）

`unittest.mock` を使い、モジュールグローバルを patch して将来の migration をシミュレートする:

```python
def test_migration_applies_pending_scripts(self) -> None:
    migration = "ALTER TABLE alpacahack_user ADD COLUMN note TEXT"
    with (
        mock.patch("bot.db.CURRENT_SCHEMA_VERSION", 2),
        mock.patch.dict("bot.db._MIGRATIONS", {1: migration}),
    ):
        Database(self.path)
    with sqlite3.connect(self.path) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(alpacahack_user)")
        }
    self.assertEqual(version, 2)
    self.assertIn("note", columns)


def test_migration_missing_path_raises(self) -> None:
    with mock.patch("bot.db.CURRENT_SCHEMA_VERSION", 2):
        with self.assertRaises(RepositoryError):
            Database(self.path)
```

`setUp` が `self.path` に version 1 の DB を作成済みなので、そのまま「既存 DB の移行」を再現できる。

### 受け入れ条件

- 上記 2 テストを含め `tests/test_db.py` が全てパスする（`test_version_mismatch`, `test_unmanaged_database_raises` は変更不要でパスするはず）

---

## タスク 3: close フローの冪等化（最重要バグ修正）

**対象**: `src/bot/features/ctf_team/discord_ops.py`, `src/bot/features/ctf_team/cog.py`, `tests/test_ctf_team_close.py`（新規）

**背景（現在のバグ）**: `_close_campaign_resources`（`cog.py`）は最初に `send_close_snapshot`（メンバー全員メンション付きの終了通知）を送り、その後 `mark_message_closed` / `delete_voice_channel` のいずれかが失敗すると DB を更新せず中断する。campaign が active のまま残るため、毎分ループ `close_expired_campaigns` が翌分また拾い、**snapshot が毎分無限に再送される**。さらに `mark_message_closed` は募集メッセージが手動削除済み（`NotFound`）のとき恒久的に失敗扱いになるため、この状態が永続する。

仕様は `docs/features/ctf-team.md` の「close 処理の順序（冪等性保証）」、設計原則は `docs/design.md` の「定期ループから呼ばれる処理は冪等にする」を参照。

### 3-1. `mark_message_closed` の `NotFound` を成功扱いにする

`discord_ops.py` の `mark_message_closed` の except 節を分割する:

```python
async def mark_message_closed(
    channel: discord.TextChannel,
    message_id: int,
) -> bool:
    try:
        message = await channel.fetch_message(message_id)
        if message.content.startswith(CLOSED_HEADER):
            return True
        await message.edit(content=f"{CLOSED_HEADER}\n\n{message.content}")
        return True
    except discord.NotFound:
        return True
    except discord.Forbidden, discord.HTTPException:
        logger.warning("Failed to mark recruitment message %s closed", message_id)
        return False
```

（同ファイルの `delete_voice_channel` が既に `NotFound` を成功扱いしており、それと整合させる。）

### 3-2. `_close_campaign_resources` の処理順を入れ替える

`cog.py` の `_close_campaign_resources` を以下に置き換える。変更点は (a) snapshot 送信を **DB 更新成功後** に移動、(b) `close_campaign` が `False`（既に closed）のときは snapshot を送らない:

```python
async def _close_campaign_resources(
    self, guild: discord.Guild, item: Campaign
) -> int | None:
    closed_at, archive_at = campaign.calculate_close(self.settings.tzinfo)

    ok = True
    recruit_ch = guild.get_channel(item.channel_id)
    if isinstance(recruit_ch, discord.TextChannel):
        ok = await discord_ops.mark_message_closed(recruit_ch, item.message_id)
    ok = (
        await discord_ops.delete_voice_channel(
            self.bot, guild, item.voice_channel_id
        )
        and ok
    )
    if not ok:
        logger.warning("Failed to close Discord resources for campaign %s", item.id)
        return None

    was_closed = await asyncio.to_thread(
        self.db.close_campaign, item.id, closed_at, archive_at
    )
    if not was_closed:
        return item.archive_at_unix or archive_at

    disc_ch = guild.get_channel(item.discussion_channel_id or 0)
    role = guild.get_role(item.role_id)
    if isinstance(disc_ch, discord.TextChannel) and role is not None:
        await discord_ops.send_close_snapshot(disc_ch, item.ctf_name, role)
    return archive_at
```

戻り値の意味（`int | None` = archive 予定時刻 / 失敗）は変えない。呼び出し側（`close_campaign_cmd`, `on_raw_reaction_add`, `close_expired_campaigns`）の変更は不要。

### 3-3. テスト追加（`tests/test_ctf_team_close.py` 新規）

`unittest.IsolatedAsyncioTestCase` を使う。cog は `CTFTeamCampaigns.__new__(CTFTeamCampaigns)` で `__init__` をバイパスして生成し、必要な属性だけ差し込む。DB は `tests/test_db.py` と同じ一時ファイルパターンで実物を使う。骨子:

```python
import asyncio
import datetime
import os
import tempfile
import unittest
from contextlib import suppress
from types import SimpleNamespace
from unittest import mock

import discord

from bot.db import Database
from bot.features.ctf_team import discord_ops
from bot.features.ctf_team.cog import CTFTeamCampaigns


class CloseCampaignResourcesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.db = Database(self.path)
        self.item = self.db.create_campaign(
            guild_id=1,
            channel_id=2,
            message_id=3,
            role_id=4,
            discussion_channel_id=5,
            voice_channel_id=6,
            ctf_name="Example",
            start_at_unix=100,
            end_at_unix=200,
            created_by=7,
            created_at_unix=90,
        )
        self.cog = CTFTeamCampaigns.__new__(CTFTeamCampaigns)
        self.cog.bot = mock.Mock()
        self.cog.settings = SimpleNamespace(tzinfo=datetime.UTC)
        self.cog.db = self.db

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            with suppress(FileNotFoundError):
                os.unlink(self.path + suffix)

    def make_guild(self) -> mock.Mock:
        guild = mock.Mock(spec=discord.Guild)
        channels = {
            2: mock.Mock(spec=discord.TextChannel),
            5: mock.Mock(spec=discord.TextChannel),
        }
        guild.get_channel.side_effect = channels.get
        guild.get_role.return_value = mock.Mock(spec=discord.Role)
        return guild
```

テストケース（`discord_ops.mark_message_closed` / `delete_voice_channel` / `send_close_snapshot` は `mock.patch.object(discord_ops, ..., new=mock.AsyncMock(...))` で差し替える）:

1. **`test_first_close_sends_snapshot_once`** — 3 関数とも成功（`mark`/`delete` は `True`、`snapshot` は `(0, True)`）で `_close_campaign_resources` を呼ぶ。戻り値が `int`、DB 上で campaign が closed になっている、`send_close_snapshot` の await 回数が 1 回であることを確認
2. **`test_retry_after_close_does_not_resend_snapshot`** — 1 と同じセットアップで 2 回連続で呼ぶ。2 回目も戻り値は `int` だが、`send_close_snapshot` の合計 await 回数が 1 回のままであることを確認（毎分ループのリトライで snapshot がスパムされない、という今回の修正の核心）
3. **`test_discord_failure_keeps_campaign_active`** — `mark_message_closed` を `False` にする。戻り値が `None`、DB 上で campaign が active のまま、`send_close_snapshot` が一度も呼ばれないことを確認

### 受け入れ条件

- 上記 3 テストがパスする
- `mark_message_closed` の `NotFound` 成功扱いはタスク 8 のテストで検証する

---

## タスク 4: 週次通知の二重送信修正

**対象**: `src/bot/features/alpacahack.py`, `src/bot/features/ctftime.py`

**背景**: `tasks.loop(hours=24)` の loop は start 後の最初のイテレーションを**即時実行**する。`change_interval(time=...)` は次のイテレーションからしか効かないため、`before_loop` 内で呼んでいる現在の実装では、bot を該当曜日（alpaca=日曜、ctftime=月曜）に再起動すると「起動直後に 1 回 + 指定時刻に 1 回」の二重送信になる。時刻指定の loop は最初から指定時刻まで待つので、**start 前に時刻を設定すれば直る**。

### 4-1. `alpacahack.py`

`Alpacahack.__init__` の `self.weekly_solve_report.start()` の**直前**に 1 行追加:

```python
self.weekly_solve_report.change_interval(time=self.settings.alpacahack_solve_time)
self.weekly_solve_report.start()
```

`before_weekly_solve`（before_loop）からは `change_interval` の呼び出しを削除し、`await self.bot.wait_until_ready()` だけを残す。

### 4-2. `ctftime.py`

同じパターン。`CTFTimeNotifications.__init__` の `.start()` 直前で:

```python
self.weekly_ctf_notification.change_interval(
    time=self.settings.ctftime_notification_time
)
self.weekly_ctf_notification.start()
```

`before_weekly` は `await self.bot.wait_until_ready()` のみ残す。

### 受け入れ条件

- 両ファイルの `before_loop` に `change_interval` が残っていない
- 自動テストは不要（discord.py の loop スケジューリングは実機確認領域。実 bot の起動確認は人間が行う）

---

## タスク 5: `/times create` の作成上限

**対象**: `src/bot/features/times.py`

**背景**: 現在はカンマ区切りの個数に上限がなく、1 コマンドで大量のチャンネル作成（Discord API rate limit の直撃）が可能。仕様は `docs/features/times.md` を参照。

### 変更内容

1. モジュール定数を追加: `MAX_CHANNELS_PER_COMMAND = 10`
2. `requested` の構築を**順序を保った重複除去**にする:

```python
requested = list(
    dict.fromkeys(
        normalized
        for raw in re.split(r"[,、\n]+", names)
        if (normalized := _normalize_channel_name(raw))
    )
)
```

3. 空チェック（既存）の**後**に上限チェックを追加。超過時は何も作成せず中断:

```python
if len(requested) > MAX_CHANNELS_PER_COMMAND:
    await send_interaction(
        interaction, "一度に作成できるチャンネルは 10 個までです。"
    )
    return
```

### 受け入れ条件

- 11 個以上指定時にチャンネルが 1 つも作成されずエラーメッセージが返る実装になっている
- 同名を複数回指定しても 1 回だけ処理される

---

## タスク 6: `Database.list_campaigns` の型統一

**対象**: `src/bot/db.py`, `src/bot/features/ctf_team/cog.py`, `tests/test_db.py`

**背景**: `find_campaign_by_name` は `status: CampaignStatus` を受けるのに、`list_campaigns` だけ `status: str | None`。DB 境界の型が不統一で、typo が型チェックで捕まらない。

### 変更内容

`db.py`:

```python
def list_campaigns(
    self, guild_id: int, status: CampaignStatus | None, limit: int = 20
) -> list[Campaign]:
    if status is None:
        return self._list(
            "WHERE guild_id=? ORDER BY created_at_unix DESC LIMIT ?",
            (guild_id, limit),
        )
    return self._list(
        "WHERE guild_id=? AND status=? ORDER BY created_at_unix DESC LIMIT ?",
        (guild_id, status.value, limit),
    )
```

`cog.py` の `list_campaigns` コマンド内、変換部分を変更:

```python
filter_status = None if status == "all" else CampaignStatus(status)
```

（`status` は `app_commands.choices` で `"active" | "closed" | "all"` に制限されているため `CampaignStatus(status)` は失敗しない。）

`tests/test_db.py` の `test_list_campaigns_filters_status_and_orders_desc` で `"active"` / `"closed"` を渡している 2 箇所を `CampaignStatus.ACTIVE` / `CampaignStatus.CLOSED` に変更する。

### 受け入れ条件

- `uv run ty check` がパスする（str を渡す箇所が残っていれば型エラーになる）

---

## タスク 7: アーキテクチャテストの拡充

**対象**: `tests/test_architecture.py`

**背景**: `db.py`（コア層）→ `features/ctf_team/models.py` という依存は意図的に許可されている（docs/design.md「依存ルール」参照）が、その安全条件「models.py は discord 非依存」「db.py が feature から import してよいのは models のみ」が機械検証されていない。

### 変更内容

`ArchitectureTest` に 2 テストを追加する:

```python
def test_feature_models_do_not_import_discord(self) -> None:
    for path in (SRC / "features").rglob("models.py"):
        imports = imports_for(path)
        self.assertFalse(
            any(
                name == "discord" or name.startswith("discord.")
                for name in imports
            ),
            f"{path} imports discord",
        )


def test_db_feature_imports_are_models_only(self) -> None:
    imports = imports_for(SRC / "db.py")
    feature_imports = {
        name for name in imports if name.startswith("bot.features.")
    }
    for name in feature_imports:
        self.assertTrue(name.endswith(".models"), f"db.py imports {name}")
```

### 受け入れ条件

- 現行コードで両テストがパスする（現状違反はないはず。違反が見つかった場合は実装を直すのではなく報告すること）

---

## タスク 8: discord_ops 純粋関数のテスト追加

**対象**: `tests/test_discord_ops.py`（新規）

**背景**: `discord_ops.py` の文字列処理関数は境界値が多い（100 文字切り詰め、連番サフィックス、1700 文字チャンク分割）のに未テスト。仕様は `docs/features/ctf-team.md` の「Discord リソース操作」節を参照。

### テスト内容

`unittest.TestCase` + `unittest.IsolatedAsyncioTestCase`（mark_message_closed 用）で以下をカバーする:

**`normalize_channel_name`**:
- 大文字・スペース混在 → lowercase / `-` 化（例: `"My CTF 2026"` → `"my-ctf-2026"`）
- 記号除去と連続 `-` の圧縮（例: `"a!!b--c"` → `"a-b-c"`）
- 全部記号 → フォールバック `"ctf"`
- 100 文字超 → 100 文字に切り詰め

**`pick_unique_channel_name`**:
- カテゴリは `mock.Mock()` に `channels = [SimpleNamespace(name=...), ...]` を設定して作る
- 重複なし → base がそのまま返る
- base が既存 → `base-2`、`base-2` も既存 → `base-3`
- 100 文字の base が既存のとき、サフィックス付きでも 100 文字以内に収まる

**`_chunk_mentions`**:
- 空リスト → `[]`
- 少数のメンション → 1 チャンクにスペース結合
- 合計 1700 文字を超える入力 → 複数チャンクに分割され、各チャンクが 1700 文字以下、順序が保たれ、全メンションが失われない

**`build_recruitment_message`**:
- `role` / `discussion_channel` は `mock.Mock()` に `mention` 属性（例: `"<@&4>"`, `"<#5>"`)を設定
- `end_at_unix` あり → `<t:...:f>` 形式が含まれる
- `end_at_unix=None` → `"常設"` が含まれる

**`mark_message_closed`**（タスク 3 の修正の検証。async テスト）:
- `channel = mock.Mock(spec=discord.TextChannel)` を使う
- `fetch_message` が `discord.NotFound(mock.Mock(status=404, reason="Not Found"), "not found")` を raise → `True`
- `fetch_message` が `discord.Forbidden(mock.Mock(status=403, reason="Forbidden"), "forbidden")` を raise → `False`
- メッセージ content が既に `CLOSED_HEADER` で始まる → `True` を返し `edit` は呼ばれない

### 受け入れ条件

- 新規テストが全てパスする

---

## 完了条件（全タスク共通）

以下 3 コマンドが全てパスすること:

```bash
uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
uv run ty check
uv run python -m unittest discover -s tests -v
```

**bot の実行（`uv run python src/main.py`）は行わないこと**（AGENTS.md 参照）。

## スコープ外（やらないこと）

- `#role` チャンネル / `times` カテゴリの名前解決を env の ID ベースに変える変更（運用側の設定変更を伴うため別途判断）
- `idx_campaign_guild_message` インデックスの整理（実害なし。次のスキーマ変更時に実施）
- docs/ 以下・AGENTS.md・README.md の編集（目標状態に更新済み）
