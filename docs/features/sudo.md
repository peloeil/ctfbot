# 一時的な管理者昇格 (sudo)

## 概要

`/sudo` で自分に既存の管理者ロール（`ADMIN_ROLE_ID`）を一時付与し、`/unsudo` または有効期限到達で自動剥奪する。日常は最小権限で過ごし、必要なときだけ昇格することで事故（誤削除・誤メンション等）を防ぐ。

## ファイル構成

| ファイル | 責務 |
|---|---|
| `models.py` | `SudoGrant` データモデル（discord 非依存） |
| `cog.py` | `/sudo`・`/unsudo` コマンド、期限切れ自動剥奪タスク |

## 認可

`/sudo` は `SUDOER_ROLE_ID` のロール（sudoer ロール）を保持するメンバーのみ実行できる。管理者権限の付与はサーバー破壊につながるため、「コマンドは原則全メンバーに開放」という認可ポリシー（`docs/design.md`）の例外とし、悪意への防御として fail-closed に倒す。加えて:

- 有効期限による自動剥奪（bot 再起動をまたいでも DB レコードにより保証）
- `log_audit` による BOT_CHANNEL への実行記録（`docs/core.md`）

ロールの判定・解決は名前ではなく必ず ID で行う。`/ctfteam open <任意の名前>` が入力名そのままのロールを作成し ✅ リアクションで誰にでも付与するため、ロール名は任意のメンバーが偽造できる。ID は偽造できない。

`/unsudo` は sudoer チェックを行わない。降格は常に許可する（昇格中に sudoer ロールを剥奪されたメンバーが自力で降格できる必要がある）。

## コマンド

### `/sudo`

1. guild 内実行を確認（`require_guild`）
2. `ADMIN_ROLE_ID` / `SUDOER_ROLE_ID` が未設定なら「sudo 機能が設定されていません。」で中断
3. 実行者が `SUDOER_ROLE_ID` のロールを保持していなければ「このコマンドを実行するには sudoer ロールが必要です。」で中断
4. guild に `ADMIN_ROLE_ID` のロールが存在しなければ「付与対象のロールが見つかりません。」で中断
5. grant レコードがあれば、設定変更後もレコードの `role_id` を今回の付与対象として維持する。保存されたロールが削除済みなら古いレコードを削除し、現在の `ADMIN_ROLE_ID` を新規 grant として扱う
6. 実行者が付与対象ロールを既に保持しているのに grant レコードがない（bot を介さない恒常保持者）場合は「既に管理者ロールを保持しています。」で中断。恒常保持を期限付き grant に変換して自動剥奪してしまわないため
7. `expires_at_unix = now + SUDO_DURATION_MINUTES * 60` として DB に grant レコードを upsert
8. 実行者が付与対象ロールを保持していなければロールを付与（`member.add_roles`）
9. 付与に失敗（`discord.Forbidden`・`discord.HTTPException`）した場合、新規 grant ならレコードを削除し、更新 grant なら更新前のレコードに戻す。その後「ロールを付与できません。bot のロール権限と順位を確認してください(`/perms`)。」で中断
10. ephemeral 応答 + `log_audit(command_name="sudo", details=["管理者ロール期限: <t:{expires_at_unix}:f>"])`

既に昇格中の場合も同じ流れで、有効期限が `now + SUDO_DURATION_MINUTES * 60` に更新される（Unix sudo のタイムスタンプ更新と同じ挙動）。`granted_at_unix` は初回付与時の値を維持する。

処理順序の理由: ロール付与より先に DB へ記録する。逆順だと「付与成功 → DB 書き込み失敗」で剥奪されない永続昇格が残る。DB 記録後に新規付与が失敗した場合はレコード削除を試み、削除に失敗しても自動剥奪タスクが回収する。

### `/unsudo`

1. guild 内実行を確認（`require_guild`）
2. 実行者が `discord.Member` でない、または自分の grant レコードがなければ「昇格中ではありません。」で中断
3. レコードに保存された `role_id` のロールを剥奪（`member.remove_roles`）。ロールが guild から削除済みの場合、および `remove_roles` が `discord.NotFound` の場合は剥奪成功として扱う
4. 剥奪に失敗（`discord.Forbidden`・`discord.HTTPException`）したら「ロールを解除できません。bot のロール権限と順位を確認してください(`/perms`)。」で中断（レコードは残し、自動剥奪タスクのリトライに委ねる）
5. grant レコードを削除
6. ephemeral 応答 + `log_audit(command_name="unsudo", details=["管理者ロールID: {grant.role_id}"])`

処理順序の理由: ロール剥奪より先にレコードを消すと「レコードなし・ロールあり」の剥奪漏れが残る。剥奪成功までレコードを残すことでリトライ可能にする。

手動で（bot を介さず）付与された管理者ロールの剥奪は対象外。bot は自身が付与した grant のみ管理する。

## バックグラウンドタスク（1分間隔）

| タスク | 内容 |
|---|---|
| `revoke_expired_grants` | `expires_at_unix` が到達した grant のロールを剥奪し、レコードを削除する |

各 grant について:

1. guild を解決できなければスキップ（次回リトライ）
2. メンバーを解決する。キャッシュになければ `guild.fetch_member` で照会し、`discord.NotFound`（退出済み）の場合のみレコードを削除する。照会自体の失敗（`discord.Forbidden`・`discord.HTTPException`）は退出と区別し、レコードを残して次回リトライ
3. レコードの `role_id` が guild に存在しなければ剥奪成功として扱う
4. ロールを剥奪（`discord.NotFound` は剥奪成功扱い） → レコード削除。剥奪失敗（`discord.Forbidden`・`discord.HTTPException`）ならレコードを残して次回リトライ
5. 剥奪したら BOT_CHANNEL に自動剥奪の通知を送る（`AllowedMentions.none()` 付き、ロックの外で送信。送信失敗は剥奪を巻き戻さない）

bot 停止中に期限が切れた grant は、再起動後の初回実行で剥奪される。

`/sudo`・`/unsudo`・自動剥奪は `(guild_id, user_id)` ごとに直列化する。自動剥奪は期限切れ一覧の取得後、ロック内で最新レコードを再取得し、更新後の期限が未到達なら処理しない。これにより、期限更新と古い期限切れスナップショットが競合して更新済み grant を削除することを防ぐ。

## データモデル

`SudoGrant` の定義は `docs/data-contracts.md`「sudo」を正本とする。

`role_id` は付与時点の `ADMIN_ROLE_ID` を保存し、grant が有効な間は設定変更を反映せず維持する。即座に反映すると、実際に付与したロールが追跡対象から外れて剥奪されないため。剥奪（`/unsudo`・自動剥奪）はこの ID を使い、新しい設定値は次回の新規付与から使われる。

## DB スキーマ

テーブル `sudo_grant` の DDL と `Database` メソッドの契約は `docs/data-contracts.md` を正本とする（version 2 → 3 の移行にも登録）。設計上のポイント:

- PRIMARY KEY は `(guild_id, user_id)`（1 ユーザー同時 1 grant）
- `expires_at_unix` に index（期限切れ一覧の取得用）
- upsert は `ON CONFLICT (guild_id, user_id) DO UPDATE` で `role_id` と `expires_at_unix` のみ更新する（`granted_at_unix` は維持）

## メッセージ形式

コマンド応答はすべて ephemeral。

| 場面 | メッセージ |
|---|---|
| 昇格成功 | `⏫ 管理者ロールを付与しました。<t:{expires}:R> に自動解除されます。` |
| 昇格延長（昇格中に再実行） | `⏫ 有効期限を <t:{expires}:R> に延長しました。` |
| 解除成功 | `⏬ 管理者ロールを解除しました。` |
| 昇格していない | `昇格中ではありません。` |
| sudoer ロールなし | `このコマンドを実行するには sudoer ロールが必要です。` |
| 未設定 | `sudo 機能が設定されていません。` |
| 付与対象ロール不在 | `付与対象のロールが見つかりません。` |
| 恒常保持者が実行 | `既に管理者ロールを保持しています。` |
| 付与失敗 | `ロールを付与できません。bot のロール権限と順位を確認してください(/perms)。` |
| 剥奪失敗 | `ロールを解除できません。bot のロール権限と順位を確認してください(/perms)。` |
| 自動剥奪通知（BOT_CHANNEL） | `⏬ {display_name} (id={user_id}) の管理者ロールを自動解除しました。` |

## 関連設定

| 環境変数 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `ADMIN_ROLE_ID` | いいえ | なし | `/sudo` で付与するロール ID。既存の管理者ロールを指定する（専用ロールの新設は不要） |
| `SUDOER_ROLE_ID` | いいえ | なし | `/sudo` を実行できるメンバーのロール ID |
| `SUDO_DURATION_MINUTES` | いいえ | 30 | 昇格の有効時間（分）。正の整数 |

`ADMIN_ROLE_ID` と `SUDOER_ROLE_ID` は両方設定するか両方未設定にする。片方だけの設定は `load_settings` で `ConfigurationError` として fail-fast する（sudoer チェック抜けの昇格を構成ミスで許さないため）。両方未設定なら機能無効。`0` は未設定として扱い（`or None` で正規化）、負値は `ConfigurationError`。

`Settings` は `admin_role_id: int | None`、`sudoer_role_id: int | None`、`sudo_duration_minutes: int` を持つ。

## Discord 側の前提

- `ADMIN_ROLE_ID`（付与対象。既存の管理者ロールでよい）と `SUDOER_ROLE_ID`（実行資格）のロールが存在すること
- bot に `manage_roles` 権限があること
- bot の最上位ロールが `ADMIN_ROLE_ID` のロールより上位にあること

満たさない場合は付与・剥奪が `Forbidden` で失敗する（上記エラーメッセージで案内）。
