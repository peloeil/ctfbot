# Phase 1: 信頼性・機械的修正

`docs/tasks/2026-07-17-docs-review.md` の実装追随タスク 2〜5・15。文書（正本）が定める契約へ実装を追随させる。ユーザー向け文字列の変更はない。

対象ファイル: `src/bot/db.py`、`src/bot/helpers.py`、`src/bot/features/audit_log.py`、`src/bot/features/ctftime.py`、`src/bot/features/alpacahack.py`、`.github/workflows/ci.yml`、`tests/`

## 1. `insert_audit_log_entry` の conflict target 限定（db.py）

仕様: `docs/data-contracts.md`「audit_log_entry」— `entry_id` 重複のみを無視して `False` を返し、それ以外の制約違反は `RepositoryError` として観測できること。

`Database.insert_audit_log_entry` の SQL を変更する:

```python
# 現在
"INSERT OR IGNORE INTO audit_log_entry ("
# 変更後
"INSERT INTO audit_log_entry ("
```

とし、VALUES 句の後に conflict 句を付ける:

```python
") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (entry_id) DO NOTHING",
```

戻り値のロジック（`cur.rowcount > 0`）は変更しない。`sqlite3.IntegrityError` は `_connection` が `RepositoryError` に変換するため追加の except は不要。

## 2. `resolve_messageable` の解決失敗 warning（helpers.py）

仕様: `docs/core.md`「チャンネルへの通知」— 解決失敗（未設定を除く）は warning ログを 1 行残す。

`resolve_messageable` を次の挙動にする（`logger` は import 済み）:

- `fetch_channel` が `NotFound` / `Forbidden` / `HTTPException` で失敗した場合: `logger.warning("Failed to resolve channel %s", channel_id)` を出して `None`
- 解決できたが `discord.abc.Messageable` でない場合: `logger.warning("Channel %s is not messageable", channel_id)` を出して `None`
- `channel_id is None` の場合は従来どおりログなしで `None`

## 3. audit_log の例外捕捉範囲拡大（features/audit_log.py）

仕様: `docs/features/audit-log.md` イベント処理 5 — 変換（`json.dumps`・`str()`）と挿入を含む処理全体の例外を `logger.error` で記録し、raise しない。

`on_audit_log_entry_create` で、現在 try の外にある `changes_json = json.dumps(...)` を try の中へ移し、except を広げる:

```python
except Exception as exc:
    logger.error("Failed to save audit log entry %s: %s", entry.id, exc)
```

ログの書式・引数は現行と同一を維持する（except 型のみ `RepositoryError` → `Exception`）。

## 4. 週次ループの例外保護（features/ctftime.py・features/alpacahack.py）

仕様: `docs/design.md`「定期ループから呼ばれる処理は冪等にする」ループの共通契約 — ループ本体はイテレーション全体を `except Exception` で捕捉してログし、ループを停止させない。`ctf_team`・`sudo` のループは実装済みで、同じパターンに揃える。

- `CTFTimeNotifications.weekly_ctf_notification`: 本体全体を `try:` で包み、末尾に

  ```python
  except Exception:
      logger.exception("Error in weekly_ctf_notification")
  ```

  を置く。内側の `except ExternalAPIError` ブロック（ログ + チャンネルへの失敗メッセージ送信）はそのまま維持する
- `Alpacahack.weekly_solve_report`: 同様に本体全体を包み `logger.exception("Error in weekly_solve_report")`。`alpacahack.py` には logger が無いため `from bot.log import logger` を追加する

## 5. CI の lockfile 固定（.github/workflows/ci.yml）

仕様: `docs/ci.md` — ワークフロー定義ブロックが正本。3 ジョブすべての `uv sync --group dev` を `uv sync --frozen --group dev` に変更する。変更後の `ci.yml` が `docs/ci.md` の YAML ブロックと一致すること。

## 受け入れ条件

- `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`・`uv run ty check`・`uv run python -m unittest discover -s tests -v` がすべてパスする
- テスト追加（テスト名は振る舞いを記述する。AGENTS.md「情報の書き分け原則」）:
  - `insert_audit_log_entry`: `entry_id` 重複で `False` を返す（既存テストがあれば維持）／`entry_id` 以外の制約違反（例: `action=None`）で `RepositoryError` を raise する
  - audit_log ハンドラ: JSON 化できない値を含むエントリでも例外が漏れない（`tests/test_audit_log.py` のスタイルに合わせる）
- ユーザー向けメッセージ文字列・既存ログ書式に変更がないこと（新規は warning 2 種と exception 2 種のみ）

## スコープ外

- `add_alpacahack_user` の `INSERT OR IGNORE`（対象テーブルは UNIQUE(name) のみで契約上の問題がなく、現状維持）
- guild チェックの追加（Phase 2）
- Embed・入力の上限（Phase 3）
