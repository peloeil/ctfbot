# 一時的な管理者昇格 (sudo)

## 概要

`/sudo` で自分に既存の管理者ロール(`ADMIN_ROLE_ID`)を一時付与し、`/unsudo` または有効期限到達で自動剥奪する。日常は最小権限で過ごし、必要なときだけ昇格することで事故(誤削除・誤メンション等)を防ぐ。

## ファイル構成

| ファイル | 責務 |
|---|---|
| `models.py` | `SudoGrant` データモデル(discord 非依存) |
| `cog.py` | `/sudo`・`/unsudo` コマンド、期限切れ自動剥奪タスク |

## 認可

`/sudo` は `SUDOER_ROLE_ID` のロール(sudoer ロール)を保持するメンバーのみ実行できる。管理者権限の付与はサーバー破壊につながるため、「コマンドは原則全メンバーに開放」という認可ポリシー(`docs/design.md`)の例外とし、悪意への防御として fail-closed に倒す。加えて:

- 有効期限による自動剥奪(bot 再起動をまたいでも DB レコードにより保証)
- `log_audit` による BOT_CHANNEL への実行記録

ロールの判定・解決は名前ではなく必ず ID で行う。`/ctfteam open <任意の名前>` が入力名そのままのロールを作成し ✅ リアクションで誰にでも付与するため、ロール名は任意のメンバーが偽造できる。ID は偽造できない。

`/unsudo` は sudoer チェックを行わない。降格は常に許可する(昇格中に sudoer ロールを剥奪されたメンバーが自力で降格できる必要がある)。

## コマンド

### `/sudo`

1. guild 内実行を確認(`require_guild`)
2. `ADMIN_ROLE_ID` / `SUDOER_ROLE_ID` が未設定なら「sudo 機能が設定されていません。」で中断
3. 実行者が `SUDOER_ROLE_ID` のロールを保持していなければ「このコマンドを実行するには sudoer ロールが必要です。」で中断
4. guild に `ADMIN_ROLE_ID` のロールが存在しなければ「付与対象のロールが見つかりません。」で中断
5. 実行者が既にロールを保持しているのに grant レコードがない(bot を介さない恒常保持者)場合は「既に管理者ロールを保持しています。」で中断。恒常保持を期限付き grant に変換して自動剥奪してしまわないため
6. `expires_at_unix = now + SUDO_DURATION_MINUTES * 60` として DB に grant レコードを upsert
7. 実行者にロールを付与(`member.add_roles`)
8. 付与に失敗(`discord.Forbidden` 等)したら grant レコードを削除し「ロールを付与できません。bot のロール権限と順位を確認してください(`/perms`)。」で中断
9. ephemeral 応答 + `log_audit`

既に昇格中の場合も同じ流れで、有効期限が `now + SUDO_DURATION_MINUTES * 60` に更新される(Unix sudo のタイムスタンプ更新と同じ挙動)。`granted_at_unix` は初回付与時の値を維持する。

処理順序の理由: ロール付与より先に DB へ記録する。逆順だと「付与成功 → DB 書き込み失敗」で剥奪されない永続昇格が残る。DB 記録後に付与が失敗した場合はレコード削除を試み、削除に失敗しても自動剥奪タスクが回収する(剥奪は冪等)。

### `/unsudo`

1. guild 内実行を確認(`require_guild`)
2. 自分の grant レコードがなければ「昇格中ではありません。」で中断
3. レコードに保存された `role_id` のロールを剥奪(`member.remove_roles`)。ロールが guild から削除済みの場合は剥奪成功として扱う
4. 剥奪に失敗(`discord.Forbidden` 等)したら「ロールを解除できません。bot のロール権限と順位を確認してください(`/perms`)。」で中断(レコードは残し、自動剥奪タスクのリトライに委ねる)
5. grant レコードを削除
6. ephemeral 応答 + `log_audit`

処理順序の理由: ロール剥奪より先にレコードを消すと「レコードなし・ロールあり」の剥奪漏れが残る。剥奪成功までレコードを残すことでリトライ可能にする。

手動で(bot を介さず)付与された管理者ロールの剥奪は対象外。bot は自身が付与した grant のみ管理する。

## バックグラウンドタスク(1分間隔)

| タスク | 内容 |
|---|---|
| `revoke_expired_grants` | `expires_at_unix` が到達した grant のロールを剥奪し、レコードを削除する |

各 grant について:

1. guild を解決できなければスキップ(次回リトライ)
2. メンバーが guild にいなければ(退出済み)レコードのみ削除
3. レコードの `role_id` が guild に存在しなければ剥奪成功として扱う
4. ロールを剥奪 → レコード削除。剥奪失敗ならレコードを残して次回リトライ
5. 剥奪したら BOT_CHANNEL に自動剥奪の通知を送る(送信失敗は剥奪を巻き戻さない)

bot 停止中に期限が切れた grant は、再起動後の初回実行で剥奪される。

## データモデル

### SudoGrant

```python
@dataclass(frozen=True, slots=True)
class SudoGrant:
    guild_id: int
    user_id: int
    role_id: int
    granted_at_unix: int
    expires_at_unix: int
```

`role_id` は付与時点の `ADMIN_ROLE_ID` を保存する。設定変更後でも、実際に付与したロールを正確に剥奪するため。剥奪(`/unsudo`・自動剥奪)はこの ID を使う。

## DB スキーマ

```sql
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

schema version 2 → 3。upsert は `ON CONFLICT (guild_id, user_id) DO UPDATE` で `role_id` と `expires_at_unix` のみ更新する(`granted_at_unix` は維持)。

Database メソッド:

- `upsert_sudo_grant(guild_id, user_id, role_id, granted_at_unix, expires_at_unix) -> SudoGrant`
- `get_sudo_grant(guild_id, user_id) -> SudoGrant | None`
- `delete_sudo_grant(guild_id, user_id) -> None`
- `list_expired_sudo_grants(now_unix) -> list[SudoGrant]`

## メッセージ形式

コマンド応答はすべて ephemeral。

| 場面 | メッセージ |
|---|---|
| 昇格成功 | `⏫ 管理者ロールを付与しました。<t:{expires}:R> に自動解除されます。` |
| 昇格延長(昇格中に再実行) | `⏫ 有効期限を <t:{expires}:R> に延長しました。` |
| 解除成功 | `⏬ 管理者ロールを解除しました。` |
| 昇格していない | `昇格中ではありません。` |
| sudoer ロールなし | `このコマンドを実行するには sudoer ロールが必要です。` |
| 未設定 | `sudo 機能が設定されていません。` |
| 付与対象ロール不在 | `付与対象のロールが見つかりません。` |
| 恒常保持者が実行 | `既に管理者ロールを保持しています。` |
| 付与失敗 | `ロールを付与できません。bot のロール権限と順位を確認してください(/perms)。` |
| 剥奪失敗 | `ロールを解除できません。bot のロール権限と順位を確認してください(/perms)。` |
| 自動剥奪通知(BOT_CHANNEL) | `⏬ {display_name} (id={user_id}) の管理者ロールを自動解除しました。` |

## 関連設定

| 環境変数 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `ADMIN_ROLE_ID` | いいえ | なし | `/sudo` で付与するロール ID。既存の管理者ロールを指定する(専用ロールの新設は不要) |
| `SUDOER_ROLE_ID` | いいえ | なし | `/sudo` を実行できるメンバーのロール ID |
| `SUDO_DURATION_MINUTES` | いいえ | 30 | 昇格の有効時間(分)。正の整数 |

`ADMIN_ROLE_ID` と `SUDOER_ROLE_ID` は両方設定するか両方未設定にする。片方だけの設定は `load_settings` で `ConfigurationError` として fail-fast する(sudoer チェック抜けの昇格を構成ミスで許さないため)。両方未設定なら機能無効。

`Settings` には `admin_role_id: int | None`、`sudoer_role_id: int | None`、`sudo_duration_minutes: int` として追加する。

## Discord 側の前提

- `ADMIN_ROLE_ID`(付与対象。既存の管理者ロールでよい)と `SUDOER_ROLE_ID`(実行資格)のロールが存在すること
- bot に `manage_roles` 権限があること
- bot の最上位ロールが `ADMIN_ROLE_ID` のロールより上位にあること

満たさない場合は付与・剥奪が `Forbidden` で失敗する(上記エラーメッセージで案内)。
