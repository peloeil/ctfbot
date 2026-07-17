# Phase 2: 認可・設定の厳格化

`docs/tasks/2026-07-17-docs-review.md` の実装追随タスク 1・6・7。Phase 1 とは独立にマージできる。

対象ファイル: `src/bot/features/utility.py`、`src/bot/features/ctftime.py`、`src/bot/features/alpacahack.py`、`src/bot/features/sudo/cog.py`、`src/bot/config.py`、`tests/`

## 1. guild 限定の徹底

仕様: `docs/core.md`「実行コンテキスト」— 全コマンドは guild 限定。guild 外（DM）では「サーバー内で実行してください。」を ephemeral で応答する。`/ctfteam`・`/sudo`・`/unsudo`・`/times create`・`/perms` は実装済み。以下を追加する。

- **`/help`（utility.py）**: ハンドラ先頭に guard を追加する。utility.py は bot 内部依存を持たない設計（`docs/design.md` 依存ルール）のため、`require_guild` を import せず `/perms` と同じ直接応答スタイルで書く:

  ```python
  if interaction.guild is None:
      await interaction.response.send_message(
          "サーバー内で実行してください。", ephemeral=True
      )
      return
  ```

- **`/ctftime`（ctftime.py `manual_ctf_check`）**: `defer()` より前に guard を追加する（`send_interaction` は import 済み）:

  ```python
  if interaction.guild is None:
      await send_interaction(interaction, "サーバー内で実行してください。")
      return
  ```

- **`/alpaca add`・`del`・`list`・`solve`（alpacahack.py）**: 4 ハンドラすべての先頭に `/ctftime` と同じ guard を追加する（`solve` は `defer()` より前）

文字列は 4 箇所とも `require_guild` と同一の「サーバー内で実行してください。」であること。

## 2. `ADMIN_ROLE_ID == SUDOER_ROLE_ID` の起動拒否（config.py）

仕様: `docs/features/sudo.md` 関連設定・`docs/data-contracts.md` 設定契約 — 同一のロール ID は `ConfigurationError` で起動拒否（同値では sudoer が常に恒常保持者となり `/sudo` が成立しないため）。

`load_settings` の既存ペア制約チェックの直後に追加する:

```python
if admin_role_id is not None and admin_role_id == sudoer_role_id:
    raise ConfigurationError(
        "ADMIN_ROLE_ID and SUDOER_ROLE_ID must be different roles."
    )
```

## 3. `/sudo` の付与対象決定順序（sudo/cog.py）

仕様: `docs/features/sudo.md` `/sudo` 手順 4〜5 — **先に grant レコードを読んで付与対象ロールの ID を決定し、その対象を解決する**。有効な grant の保存ロールが健在であれば、現在設定の `ADMIN_ROLE_ID` のロールが削除されていても延長は成立する。

現行実装は逆順（`configured_role = guild.get_role(admin_role_id)` の存在確認がロック取得・grant 読み取りより前）。次のように変更する:

- `sudo()` から先行の `configured_role` 解決と `None` チェック（「付与対象のロールが見つかりません。」raise）を削除し、ロック内の `_resolve_sudo_role` 呼び出しへ `admin_role_id: int` を渡す
- `_resolve_sudo_role` を次の契約に書き換える:

  ```python
  async def _resolve_sudo_role(
      self,
      guild: discord.Guild,
      member: discord.Member,
      admin_role_id: int,
      grant: SudoGrant | None,
  ) -> tuple[discord.Role, SudoGrant | None]:
      if grant is not None:
          granted_role = guild.get_role(grant.role_id)
          if granted_role is not None:
              return granted_role, grant
          await asyncio.to_thread(
              self.db.delete_sudo_grant, grant.guild_id, grant.user_id
          )
          grant = None

      configured_role = guild.get_role(admin_role_id)
      if configured_role is None:
          raise ServiceError("付与対象のロールが見つかりません。")
      if self._has_role(member, configured_role.id):
          raise ServiceError("既に管理者ロールを保持しています。")
      return configured_role, None
  ```

エラーメッセージ 2 種は既存文字列から変更しない。手順 6 以降（upsert・付与・失敗時の復元）は変更しない。

## 受け入れ条件

- `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`・`uv run ty check`・`uv run python -m unittest discover -s tests -v` がすべてパスする
- テスト追加・更新:
  - `tests/test_config.py`: `ADMIN_ROLE_ID == SUDOER_ROLE_ID` で `ConfigurationError`（両方未設定・別値の正常系は既存を維持）
  - `tests/test_sudo.py`: **現在設定のロールが削除済みでも、保存ロールが健在な grant の延長が成立する**（S4 の回帰テスト）／grant 無し・現在設定ロール不在で「付与対象のロールが見つかりません。」が返る（既存テストは新順序に合わせて更新）
- 既存のエラーメッセージ文字列に変更がないこと

## スコープ外

- `@app_commands.guild_only()` デコレータの採用（共通エラーハンドラの応答文字列が仕様と一致しなくなるため、ランタイムチェック方式に統一する）
- クールダウン・入力検証（Phase 3）
