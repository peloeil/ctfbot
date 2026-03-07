# AGENTS.md

このファイルは coding agent 向けです。セットアップと運用前提は `README.md`、人間向けの設計説明と開発手順は `docs/DEVELOPMENT_GUIDE.md` を参照してください。

## Hard Rules

- 依存方向は `cog -> usecase -> service/repository -> db` を維持する
- `src/bot/cogs/` から `bot.db` / `bot.services` / `bot.application` を直接 import しない
- `features/*/cog.py` から `service.py` / `repository.py` を直接 import しない
- `features/*/usecase.py` では `discord` と `bot.cogs` に依存しない
- `features/*/repository.py` は persistence 専用に保ち、`discord` を import しない
- cog 内で service / repository / usecase を直接 new せず、`get_runtime(bot)` 経由で使う
- `requests` や SQLite などの blocking I/O は service / repository に閉じ込め、cog からは `asyncio.to_thread(...)` で呼ぶ
- background task は cog の `__init__` で開始し、`cog_unload()` で必ず cancel する
- 内部例外は `bot.errors` を使い、ユーザー向けメッセージは日本語を基本にする
- README / docs / 実装に差分がある場合は `src/` と `tests/` を source of truth とし、特に `tests/` を優先する
- slash command を変更したら `/cog reload <name>` の後に `/cog sync` を行う

## 最初に見る場所

- 変更対象 feature の `src/bot/features/<feature>/`
- utility slash command の場合は `src/bot/cogs/`
- 対応する `tests/test_*.py`
- 新機能追加時は `src/bot/runtime_providers.py`, `src/bot/runtime.py`, `src/bot/cogs_loader.py`
- 設定変更時は `src/bot/config.py`
- 例外設計変更時は `src/bot/errors.py`

## 実装上の要点

- `build_connection_factory()` は起動時に migration を適用する
- schema 変更時は `src/bot/db/migrations.py` の `MIGRATIONS` に末尾追加し、既存 migration を並べ替えたり書き換えたりしない
- Discord 送信は `send_interaction_message(...)` と `send_message_safely(...)` を優先する
- logging は `ctfbot` logger を使う

## Feature-Specific Constraints

### `ctftime`

- `requests` で CTFtime API を取得する
- retry / backoff と `User-Agent` を維持する
- 定期通知は毎週月曜のみ送信する
- 既定の通知先は `BOT_CHANNEL_ID`

### `alpacahack`

- 登録ユーザーは `alpacahack_user` テーブルに保存する
- AlpacaHack のユーザーページを scrape して weekly solve を集計する
- 定期通知先は `ctf` カテゴリ配下の `#alpacahack`
- ユーザーごとの取得間に短い sleep を入れる前提

### `ctf_roles`

- 変更前に `tests/test_ctf_roles.py` を確認する
- `/ctfteam open` は role、discussion channel、voice channel、募集 message をまとめて扱う
- 募集告知は `#role` に投稿する。`#role` が無いと作成できない
- discussion / voice channel は `ctf` カテゴリ配下に作り、archive 時は `archive` カテゴリへ移動する
- reaction add で role を付与する
- reaction remove では role を外さない。role は archive 移行まで保持する
- 開始通知、終了処理、archive 処理は 1 分ループ
- 作成途中で失敗した場合は cleanup を試みる

固定されている制約:

- 作成者ごとの active 募集上限は `3`
- CTF 名の長さ上限は `60`
- active 募集の同名重複は大文字小文字を無視して拒否する
- 終了日時は開始日時より後でなければならない
- archive 予定日は close から `30` 日後

## Validation

変更範囲に応じてまず対象テストを回す。

- architecture / import 変更:
  `uv run python -m unittest tests.test_architecture -v`
- config / runtime / migration 変更:
  `uv run python -m unittest tests.test_config tests.test_runtime tests.test_db -v`
- `ctf_roles` 変更:
  `uv run python -m unittest tests.test_ctf_roles -v`
- `ctftime` 変更:
  `uv run python -m unittest tests.test_ctftime_api tests.test_cogs -v`
- utility cogs 変更:
  `uv run python -m unittest tests.test_slash_commands tests.test_cogs_loader -v`
- `alpacahack` 変更:
  `uv run python -m unittest tests.test_bot tests.test_cogs -v`

最終的には全体チェックを通す。

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run ty check
uv run python -m unittest discover -s tests -v
```

## Change Checklist

- 依存方向を壊していない
- blocking I/O を cog 直下で実行していない
- 新機能を runtime / cogs_loader に配線した
- 例外を `bot.errors` に沿って扱っている
- 対応テストを追加または更新した
- 挙動変更時に該当ドキュメントを更新した
