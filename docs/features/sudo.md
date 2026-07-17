# 一時的な管理者昇格 (sudo)

## 概要

`/sudo` で自分に既存の管理者ロール（`ADMIN_ROLE_ID`）を一時付与する。`/unsudo` で手動解除でき、有効期限到達で自動剥奪される。日常は最小権限で過ごし、必要なときだけ昇格することで事故（誤削除・誤メンション等）を防ぐ。

## ファイル構成

| ファイル | 責務 |
|---|---|
| `models.py` | `SudoGrant` データモデル（discord 非依存） |
| `cog.py` | `/sudo`・`/unsudo` コマンド、期限切れ自動剥奪タスク |

## 認可

`/sudo` は `SUDOER_ROLE_ID` のロール（sudoer ロール）を保持するメンバーのみ実行できる。管理者権限の付与はサーバー破壊につながるため、「コマンドは原則全メンバーに開放」という認可ポリシー（`docs/design.md`）の例外とし、悪意への防御として fail-closed に倒す。加えて:

- 有効期限による自動剥奪（bot 停止・剥奪失敗中は期限を越えて保持され得るが、DB レコードが残る限り復旧後の初回実行で再試行される）
- `log_audit` による BOT_CHANNEL への実行記録（`docs/core.md`）

ロールの判定・解決は名前ではなく必ず ID で行う。`/ctfteam open <任意の名前>` が入力名そのままのロールを作成し ✅ リアクションで誰にでも付与するため、ロール名は任意のメンバーが偽造できる。ID は偽造できない。

`/unsudo` は sudoer チェックを行わない。降格は常に許可する（昇格中に sudoer ロールを剥奪されたメンバーが自力で降格できる必要がある）。

## コマンド

コマンド応答はすべて ephemeral。

### `/sudo`

1. guild 内実行を確認（`require_guild`）
2. `ADMIN_ROLE_ID` / `SUDOER_ROLE_ID` が未設定なら「sudo 機能が設定されていません。」で中断
3. 実行者が `SUDOER_ROLE_ID` のロールを保持していなければ「このコマンドを実行するには sudoer ロールが必要です。」で中断
4. 自分の grant レコードを読み、付与対象ロールの ID を決定する: レコードがあれば保存された `role_id` を維持する（設定変更後も）。保存されたロールが guild から削除済みなら古いレコードを削除し、現在の `ADMIN_ROLE_ID` を新規 grant として扱う。レコードがなければ現在の `ADMIN_ROLE_ID`
5. 決定した付与対象ロールが guild に存在しなければ「付与対象のロールが見つかりません。」で中断（有効な grant の保存ロールが健在であれば、現在設定のロールが削除されていても延長は成立する）
6. 実行者が付与対象ロールを既に保持しているのに grant レコードがない（bot を介さない恒常保持者）場合は「既に管理者ロールを保持しています。」で中断。恒常保持を期限付き grant に変換して自動剥奪してしまわないため
7. `expires_at_unix = now + SUDO_DURATION_MINUTES * 60` として DB に grant レコードを upsert
8. 実行者が付与対象ロールを保持していなければロールを付与（`member.add_roles`）
9. 付与に失敗（`discord.Forbidden`・`discord.HTTPException`）した場合、新規 grant ならレコードを削除し、更新 grant なら更新前のレコードに戻す。その後「ロールを付与できません。bot のロール権限と順位を確認してください(/perms)。」で中断。レコードの削除・復元自体が失敗した場合は exception ログのみ残す（応答は同じ。残った新期限のレコードは自動剥奪タスクが期限到達時に回収する）
10. 「⏫ 管理者ロールを付与しました。<t:{expires_at_unix}:R> に自動解除されます。」（延長時は「⏫ 有効期限を <t:{expires_at_unix}:R> に延長しました。」）で応答 + `log_audit(command_name="sudo", details=["管理者ロール期限: <t:{expires_at_unix}:f>"])`

既に昇格中の場合も同じ流れで、有効期限が `now + SUDO_DURATION_MINUTES * 60` に更新される。`granted_at_unix` は初回付与時の値を維持する。

処理順序の理由: ロール付与より先に DB へ記録する。逆順だと「付与成功 → DB 書き込み失敗」で剥奪されない永続昇格が残る。DB 記録後に新規付与が失敗した場合はレコード削除を試み、削除に失敗しても自動剥奪タスクが回収する。

### `/unsudo`

1. guild 内実行を確認（`require_guild`）
2. 実行者が `discord.Member` でない、または自分の grant レコードがなければ「昇格中ではありません。」で中断
3. レコードに保存された `role_id` のロールを剥奪（`member.remove_roles`）。ロールが guild から削除済みの場合、および `remove_roles` が `discord.NotFound` の場合は剥奪成功として扱う
4. 剥奪に失敗（`discord.Forbidden`・`discord.HTTPException`）したら「ロールを解除できません。bot のロール権限と順位を確認してください(/perms)。」で中断（レコードは残し、自動剥奪タスクのリトライに委ねる）
5. grant レコードを削除
6. 「⏬ 管理者ロールを解除しました。」で応答 + `log_audit(command_name="unsudo", details=["管理者ロールID: {grant.role_id}"])`

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
5. 剥奪した場合、およびロール不在で剥奪成功扱いにした場合は、BOT_CHANNEL に「⏬ {display_name} (id={user_id}) の管理者ロールを自動解除しました。」を送る（`AllowedMentions.none()` 付き、ロックの外で送信。送信失敗は剥奪を巻き戻さない）。メンバー退出でレコードを削除した場合は送らない

bot 停止中に期限が切れた grant は、再起動後の初回実行で剥奪される。

`/sudo`・`/unsudo`・自動剥奪は `(guild_id, user_id)` ごとに直列化する。自動剥奪は期限切れ一覧の取得後、ロック内で最新レコードを再取得し、更新後の期限が未到達なら処理しない。これにより、期限更新と古い期限切れスナップショットが競合して更新済み grant を削除することを防ぐ。

## データモデル

`SudoGrant` の定義は `docs/data-contracts.md`「sudo」を正本とする。

`role_id` は付与時点の `ADMIN_ROLE_ID` を保存し、grant が有効な間は設定変更を反映せず維持する。即座に反映すると、実際に付与したロールが追跡対象から外れて剥奪されないため。剥奪（`/unsudo`・自動剥奪）はこの ID を使い、新しい設定値は次回の新規付与から使われる。

## DB スキーマ

テーブル `sudo_grant` の DDL と `Database` メソッドの契約は `docs/data-contracts.md` を正本とする。

## 関連設定

環境変数の定義は `docs/data-contracts.md`「設定契約」を正本とする。

片方だけのロール ID 設定を拒否するのは、構成ミスによる sudoer チェック抜けを防ぐためである。同一のロール ID を拒否するのは、sudoer が恒常的に管理者ロールを保持することになり、手順 6 で `/sudo` が常に拒否されるためである。

## Discord 側の前提

- `ADMIN_ROLE_ID`（付与対象）と `SUDOER_ROLE_ID`（実行資格）のロールが存在すること
- bot に `manage_roles` 権限があること
- bot の最上位ロールが `ADMIN_ROLE_ID` のロールより上位にあること

満たさない場合は付与・剥奪が `Forbidden` で失敗する（上記エラーメッセージで案内）。
