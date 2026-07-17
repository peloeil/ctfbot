# Phase 3: 表示・入力の上限

`docs/tasks/2026-07-17-docs-review.md` の実装追随タスク 8〜14。Phase 1・2 とは独立にマージできる（同一ファイルを触るが対象関数は重ならない）。

対象ファイル: `src/bot/helpers.py`、`src/bot/features/ctf_team/cog.py`、`src/bot/features/ctftime.py`、`src/bot/features/alpacahack.py`、`tests/`

## 1. リンク安全判定ヘルパー（helpers.py）

仕様: `docs/core.md`「表示テキストの escape 方針」。ctftime と alpacahack の両方で使うため helpers.py に置く（`format_timestamp` 等の純粋関数と同列。両 feature は helpers を import 済みで、依存図に新しい辺を作らない）。

```python
def is_markdown_link_safe(value: str) -> bool:
    return bool(value) and not any(ch in value for ch in "]()")
```

## 2. `/ctfteam list` の省略行込み 4096 予約（ctf_team/cog.py）

仕様: `docs/features/ctf-team.md` `/ctfteam list` — 省略行「他 {m} 件は省略しています。」を含めて description が 4096 文字に収まるよう余白を確保する。現行実装は上限判定の**後**に省略行を追加するため、境界条件で 4096 を超え得る。

`_build_campaigns_embed` のループを次の形にする（block の組み立て・書式は変更しない）:

```python
_OMISSION_RESERVE = 30  # 省略行と区切り空行の余白


    lines = [f"{len(campaigns)}件を表示しています。"]
    for index, item in enumerate(campaigns, start=1):
        block_lines = [...]  # 変更なし
        block = "\n".join(block_lines)
        limit = 4096 if index == len(campaigns) else 4096 - _OMISSION_RESERVE
        candidate = "\n\n".join([*lines, block])
        if len(candidate) > limit:
            remaining = len(campaigns) - (len(lines) - 1)
            lines.append(f"他 {remaining} 件は省略しています。")
            break
        lines.append(block)
    embed.description = "\n\n".join(lines)
```

最終要素だけ 4096 まで使えるのは、その後に省略行が続かないため。途中要素で打ち切った場合、それまでの lines は `4096 - 30` 以内に収まっており、省略行（最長でも「他 20 件は省略しています。」+ 区切り = 30 文字未満）を足しても 4096 を超えない。

## 3. CTFtime Embed の 🔗 行省略（ctftime.py）

仕様: `docs/features/ctftime.md` Embed 形式 — `ctftime_url` が空、またはリンク構文を壊す文字を含む場合は 🔗 行を出力しない（現行は壊れリンク `[CTFtime]()` を生成する）。

`_build_events_embed` のブロック組み立てを変更する（`bot.helpers` から `is_markdown_link_safe` を import）:

```python
        link_line = (
            f"\n🔗 [CTFtime]({event.ctftime_url})"
            if is_markdown_link_safe(event.ctftime_url)
            else ""
        )
        block = (
            f"**{event.title}**\n"
            f"🕐 <t:{start_unix}:f> 〜 <t:{finish_unix}:f>"
            f"{link_line}"
        )
```

## 4. AlpacaHack の入力・負荷・表示上限（alpacahack.py）

仕様: `docs/features/alpacahack.md`。新しいユーザー可視の制限を含む（値は文書が正本）。

### 4-1. username の形式検証（`/alpaca add`）

空チェックの直後に追加する。エラーメッセージは**バッククォートを文字列に含む**:

```python
_MAX_USERNAME_LENGTH = 32
_USERNAME_PATTERN = re.compile(r"[0-9A-Za-z_-]+")
```

```python
        if len(name) > _MAX_USERNAME_LENGTH or not _USERNAME_PATTERN.fullmatch(name):
            await send_interaction(
                interaction,
                "ユーザー名は 32 文字以内の英数字と `-` `_` で入力してください。",
            )
            return
```

### 4-2. 登録上限 50 人（`/alpaca add`）

`_MAX_USERS = 50` を定義し、insert 前に一覧を取得して判定する。**既登録判定を上限判定より先に行う**（上限到達時でも既登録ユーザーへの応答は従来どおり冪等にするため）:

```python
        users = await asyncio.to_thread(self.db.list_alpacahack_users)
        if name in users:
            await send_interaction(interaction, f"`{name}` は既に登録されています。")
            return
        if len(users) >= _MAX_USERS:
            await send_interaction(interaction, "登録数が上限(50人)に達しています。")
            return
        created = await asyncio.to_thread(self.db.add_alpacahack_user, name)
```

以降の分岐（`created` が False なら「`{name}` は既に登録されています。」）は競合時の保険として維持する。丸括弧は半角(上限(50人))。既存メッセージの様式（`(上限: 5)`・`(/perms)`）と ruff の RUF001（全角括弧の ambiguous 警告）に合わせる。

### 4-3. `/alpaca solve` のクールダウン

仕様: guild ごとに 60 秒 1 回。超過時は共通エラーハンドラ（`docs/core.md`）の「コマンドはクールダウン中です。」が応答する（ハンドラ実装済み・変更不要）。

```python
    @app_commands.command(name="solve", description="今週のsolve状況を表示します。")
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: i.guild_id)
    async def show_solves(...)
```

### 4-4. Embed 合計 6000 文字の打ち切り

仕様: Embed 全体（title + description + 全 field の name・value）を 6000 文字以内に収める。field 追加で超過する場合はそこで打ち切り、以降のユーザーは省略人数として最終 field に合算する。

`_build_summary_embed` に定数を導入し、field 追加ループを予算制にする:

```python
_EMBED_TOTAL_LIMIT = 6000
_FINAL_FIELD_RESERVE = 1100  # 最終 field（その他 / 取得失敗。value は最大 1024）の余白
```

```python
    total = len(embed.title or "") + len(description)
    visible_items = list(summary.weekly_solves.items())[: MAX_EMBED_FIELDS - 1]
    shown = 0
    for username, solves in visible_items:
        name = f"{username} ({len(solves)} solves)"
        value = ...  # 既存の組み立て（12 件・1024 文字切り詰め）を変更しない
        if total + len(name) + len(value) > _EMBED_TOTAL_LIMIT - _FINAL_FIELD_RESERVE:
            break
        embed.add_field(name=name, value=value, inline=False)
        total += len(name) + len(value)
        shown += 1
    omitted_users = max(len(summary.weekly_solves) - shown, 0)
```

最終 field（「その他 / 取得失敗」）の組み立ては変更しない。常に `_FINAL_FIELD_RESERVE` を確保するため、打ち切りが発生した場合は必ず最終 field が入り、合計は 6000 以内に収まる。

### 4-5. challenge リンクの非リンク化

仕様: challenge 名または URL がリンク構文を壊す文字を含む場合はリンク化せず名前のみ表示する。

value_lines の組み立てを変更する（`bot.helpers` から `is_markdown_link_safe` を import に追加）:

```python
            if (
                record.challenge_url
                and is_markdown_link_safe(record.challenge_url)
                and is_markdown_link_safe(record.challenge_name)
            ):
                value_lines.append(
                    f"- [{record.challenge_name}]({record.challenge_url})"
                )
            else:
                value_lines.append(f"- {record.challenge_name}")
```

## 受け入れ条件

- `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`・`uv run ty check`・`uv run python -m unittest discover -s tests -v` がすべてパスする
- テスト追加（振る舞いを記述する名前で）:
  - `_build_campaigns_embed`: 長い CTF 名の campaign を多数与えても description が省略行込みで 4096 文字以内になり、省略行の件数が正しい
  - `_build_events_embed`: URL が空・`)` を含むイベントで 🔗 行が出力されず、正常な URL では出力される
  - `/alpaca add` 検証: 33 文字・不正文字（`/` や日本語）で拒否メッセージ、境界値 32 文字・`-`/`_` は受理
  - 登録上限: 50 人登録済みで新規は拒否、既登録名は従来どおり「既に登録されています。」
  - `_build_summary_embed`: 24 人 × 長い value でも合計（title + description + 全 field name/value）が 6000 文字以内で、省略人数が最終 field に反映される
  - リンク非リンク化: challenge 名に `)` を含むレコードが名前のみで表示される
- 既存メッセージの文字列に変更がないこと（新規文字列は 4-1・4-2 の 2 つのみ。内容は本書の記載と完全一致）

## スコープ外

- `/alpaca list` の分割（上限導入により 2000 文字に収まる。`docs/features/alpacahack.md`）
- スクレイパーのリトライ・redirect 挙動の変更（現状維持が仕様）
- username 上限・件数上限・クールダウン値の変更（値を変える場合は先に文書を更新する）
