# /alpaca add の登録上限判定を Database API 内で atomic に行う

## 背景（何が問題か）

`docs/features/alpacahack.md` は登録数の上限を 50 人と定めるが、現在の実装は
一覧取得（`list_alpacahack_users`）→ 件数判定 → 挿入（`add_alpacahack_user`）を
別々の DB 呼び出しで行っている（`src/bot/features/alpacahack.py` の `add_user`）。
49 人の状態で異なる username の `/alpaca add` が並行すると、双方が上限未到達と
判定して挿入でき、51 人になり得る。上限判定と挿入を 1 つの Database API に
まとめ、`BEGIN IMMEDIATE` トランザクション内で atomic に行う。

あわせて、cog 内に分散していた DB 依存の検証（重複・上限）を DB API の戻り値と
例外に寄せる（`AGENTS.md` アーキテクチャ制約 8「バリデーションは例外ベース」、
`docs/design.md`「validation は境界ごとに分ける」への適合）。

## 対象ファイル

- `src/bot/db.py`
- `src/bot/features/alpacahack.py`
- `docs/data-contracts.md`（alpacahack_user の API 契約表）
- `docs/features/alpacahack.md`（`/alpaca add` の節）
- `tests/test_db.py`
- `tests/test_alpacahack.py`

DB スキーマの変更はない（`_SCHEMA_DDL`・`CURRENT_SCHEMA_VERSION`・`_MIGRATIONS`
には触れない）。

## 実装内容

### 1. `Database.add_alpacahack_user` のシグネチャと契約を変更する

```python
def add_alpacahack_user(self, name: str, *, max_users: int) -> bool:
    clean = name.strip()
    if not clean:
        raise RepositoryError("AlpacaHack username must not be empty.")
    with self._connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        exists = conn.execute(
            "SELECT 1 FROM alpacahack_user WHERE name = ?", (clean,)
        ).fetchone()
        if exists is not None:
            return False
        count = conn.execute("SELECT COUNT(*) FROM alpacahack_user").fetchone()[0]
        if count >= max_users:
            raise ConflictError("AlpacaHack user limit reached.")
        conn.execute("INSERT INTO alpacahack_user (name) VALUES (?)", (clean,))
        conn.commit()
        return True
```

契約:

- `True` = 挿入した
- `False` = 同名既存（上限到達の有無より優先して判定する。既存名の再登録は
  上限到達時でも `False` を返し、`ConflictError` にしない）
- 上限到達（`COUNT(*) >= max_users`）で新規名 → `ConflictError("AlpacaHack user limit reached.")`
- 判定と挿入は同一接続の `BEGIN IMMEDIATE` トランザクション内で行う
- `ConflictError` のメッセージは内部向け英語（ユーザーに表示しない。
  `AGENTS.md` コーディング規約「言語」）

`return False` の経路はトランザクションを commit せず抜けてよい
（`_connection` が close し、読み取りのみなのでロールバックで問題ない）。

### 2. `add_user`（cog）の DB 依存検証を置き換える

`src/bot/features/alpacahack.py` の `add_user` で、現在の

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

を次に置き換える（guild チェック・空チェック・形式チェックの応答はそのまま残す）:

```python
try:
    created = await asyncio.to_thread(
        self.db.add_alpacahack_user, name, max_users=_MAX_USERS
    )
except ConflictError:
    await send_interaction(interaction, "登録数が上限(50人)に達しています。")
    return
```

`created` が `True` / `False` の場合の応答と `log_audit` は現行のまま変えない。
`ConflictError` は `bot.errors` から import する（`ExternalAPIError` の既存 import に
並べる）。

ユーザー向け応答メッセージは 1 文字も変えないこと:

- 「`{name}` を登録しました。」
- 「`{name}` は既に登録されています。」
- 「登録数が上限(50人)に達しています。」（丸括弧は半角）

### 3. ドキュメント更新

- `docs/data-contracts.md` の alpacahack_user API 表の `add_alpacahack_user` 行を
  新契約に更新する:
  `add_alpacahack_user(name, *, max_users) -> bool` /
  `name.strip()` して挿入。strip 後空は `RepositoryError`。`BEGIN IMMEDIATE` で
  同名存在 → `False`、`COUNT(*) >= max_users`（新規名）→
  `ConflictError("AlpacaHack user limit reached.")`、それ以外は挿入して `True`
- `docs/features/alpacahack.md` の `/alpaca add` 節に、上限判定と挿入が
  Database API 内の atomic な判定であること（同時実行でも 50 人を超えない）を
  1 文追記する

### 4. テスト

`tests/test_db.py`（既存の `test_alpacahack_users` を新シグネチャに追従させた上で追加）:

- 上限到達時に新規名が `ConflictError` になること
  （例: `max_users=2` で 2 人登録後、3 人目が `ConflictError`）
- 上限到達時でも既存名は `ConflictError` ではなく `False` を返すこと
- 上限未満では従来どおり `True` / 同名 `False` が返ること

`tests/test_alpacahack.py` の `AlpacaHackCommandTest`（cog.db は `Mock`）:

- `test_add_accepts_32_character_username_with_dash_and_underscore`:
  `add_alpacahack_user` の assert を
  `assert_called_once_with(name, max_users=50)` に変更。
  `list_alpacahack_users` の `return_value` 設定は不要になるため削除
- `test_add_rejects_new_user_when_registration_limit_is_reached`:
  `self.cog.db.add_alpacahack_user.side_effect = ConflictError("AlpacaHack user limit reached.")`
  に変更し、応答「登録数が上限(50人)に達しています。」と
  `log_audit` が呼ばれないことを検証する
- `test_add_reports_existing_user_when_registration_limit_is_reached`:
  `self.cog.db.add_alpacahack_user.return_value = False` に変更し、
  応答「`alice` は既に登録されています。」と `log_audit` が呼ばれないことを検証する
- `test_add_rejects_too_long_and_invalid_usernames` 末尾の
  `list_alpacahack_users.assert_not_called()` は
  `add_alpacahack_user.assert_not_called()` に変更する

## 受け入れ条件

1. `src/` から `list_alpacahack_users` を上限・重複判定目的で呼ぶ箇所が残っていない
   （`/alpaca list` の一覧表示と `collect_weekly_summary` の利用は現行のまま残す）
2. `add_alpacahack_user` の呼び出しがすべて `max_users` キーワード引数付きである
3. 上記のユーザー向け応答メッセージ 3 種が変わっていない
4. `docs/data-contracts.md`・`docs/features/alpacahack.md` が新契約と一致している
5. 検証 3 コマンド（`AGENTS.md`「検証」）がすべてパスする

## スコープ外

- DB スキーマ変更・migration
- `/alpaca del`・`/alpaca list`・`/alpaca solve`・週次通知の挙動変更
- `_MAX_USERS`（50）の値の変更
- cog の guild・空文字・形式チェックの構造変更（現行の直接応答のまま）
