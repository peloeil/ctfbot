# 設計レビュー (2026-07-06)

対象: リポジトリ全体（src 約 2,300 行、feature 5 個 + コア 6 モジュール）
レビュアー: Claude

## レビュー方針

このリポジトリは design.md・`.claude/rules/`・`tests/test_architecture.py` で設計判断が明文化・機械検証されている。したがって一般的なコード品質ではなく、以下の観点で「宣言された設計」と「実装の現実」のずれ、および設計文書がまだカバーしていない領域を重点的に見る。

- **A. 設計文書と実装・検証機構の整合性** — design.md / rules / アーキテクチャテストは実態と一致しているか
- **B. レイヤリングと依存方向** — コア ↔ feature の依存は健全か
- **C. 状態整合性** — Discord リソースと DB の二重管理。クラッシュ・リトライ・冪等性
- **D. スケジューリング** — 週次/毎分ループの再起動時挙動
- **E. 拡張性** — 新 feature 追加・スキーマ変更のパス
- **F. 認可設計** — 誰がどのコマンドを実行できるか
- **G. テスト戦略** — 「Discord モック無しでテストしたいか」という分割基準とテストの実態

---

## 指摘事項（重要度順）

### 1. [High] close リトライが非冪等 — 失敗が固定化すると毎分スナップショットがスパムされる

**場所**: `cog.py:487-515` (`_close_campaign_resources`), `discord_ops.py:217-229` (`mark_message_closed`), `cog.py:422-432` (`close_expired_campaigns`)

`_close_campaign_resources` は次の順で動く:

1. `send_close_snapshot` — discussion チャンネルへ「🔒 終了しました + 参加メンバー全員のメンション」を**無条件に送信**
2. `mark_message_closed` / `delete_voice_channel` — どちらか失敗なら `None` を返し **DB は更新しない**（campaign は active のまま）

campaign が active のままなので `close_expired_campaigns`（毎分ループ）が翌分also拾い、手順 1 から再実行する。つまり **失敗が恒久的なら、discussion チャンネルに終了スナップショット + メンションが毎分無限に投稿される**。

恒久的失敗は現実に起きる: 募集メッセージがモデレーターに手動削除されると `fetch_message` が `NotFound` → `mark_message_closed` は `False` を返し続ける。同じファイル内の `delete_voice_channel` は `NotFound` を「既に無い = 成功」と扱っており（`discord_ops.py:183-184, 194-195`）、**NotFound の扱いが関数間で不整合**なのが直接の原因。

**改善案**:
- `mark_message_closed` の `NotFound` は成功扱いにする（対象が無い = やることが無い）
- 副作用の順序を入れ替える: 冪等な操作（message 編集・voice 削除）→ DB の `close_campaign` → 最後に snapshot 送信。snapshot が失敗しても campaign は closed になっており再送されない
- 設計原則として design.md に「毎分ループから呼ばれる処理は冪等でなければならない。非冪等な副作用（通知送信）は状態遷移の確定後に置く」を追記する

### 2. [High] スキーマ変更ルールと実装が矛盾 — migration パスが存在しない

**場所**: `db.py:76-98` (`_ensure_schema`), `.claude/rules/db-constraints.md`

db-constraints.md は「新テーブル追加時は `_SCHEMA_DDL` に DDL を追加し `CURRENT_SCHEMA_VERSION` をインクリメント」と定めるが、`_ensure_schema` は version 不一致の DB を**起動拒否するだけ**で移行手段がない。つまり **ルールに従って開発すると、既存の本番 DB が起動不能になる**。現状の設計は「新規 DB のみ version 2 になれる」であり、運用中の bot には適用できない。

**改善案**: version N → N+1 の migration 関数チェーンを db.py に持つ（`_MIGRATIONS: dict[int, str]` に ALTER 文を登録し、`_ensure_schema` が順に適用して `user_version` を進める程度で十分）。あるいは「migration は手動で ALTER + `PRAGMA user_version` を叩く」と決めるなら、その手順を README/db-constraints.md に明記する。どちらにせよ**設計として決まっていない**のが問題。

### 3. [Medium] コア → feature の依存（db.py → ctf_team/models.py）が設計文書とアーキテクチャテストの死角

**場所**: `db.py:7`, `docs/design.md` 依存ルール節, `tests/test_architecture.py`

`db.py`（コア層）が `bot.features.ctf_team.models` を import している。これは「Database を 1 クラスに集約する」という設計判断の帰結だが:

- design.md の依存ルールグラフに **この辺が記載されていない**（`db.py ✗ discord` のみ）
- `test_architecture.py` も検証していない
- feature-isolation.md は「campaign.py / **models.py** は discord を import しない」と定めるが、テストは campaign.py しか見ていない（`test_architecture.py:21-25`）

feature が増えて各自テーブルを持つようになると、db.py が全 feature の models に依存するハブになる。これは「1 クラス集約」方針の必然的なコストなので、**方針を変えるのではなく、暗黙の辺を明示化する**のがよい。

**改善案**（小規模を維持する前提の追認路線）:
- design.md の依存ルールに `db.py → <feature>/models.py（許可。ただし models.py は discord 非依存であること）` を明記
- `test_architecture.py` に「models.py が discord を import しない」テストを追加（db.py 経由で discord が漏れない保証になる）

### 4. [Medium] 週次通知が再起動時に二重送信される

**場所**: `alpacahack.py:262-284`, `ctftime.py:130-155`

`tasks.loop(hours=24)` で start し、`before_loop` 内の `change_interval(time=...)` で実行時刻を設定するパターンだが、discord.py の仕様では **最初のイテレーションは before_loop 完了直後に即時実行**され、`change_interval` は次イテレーションから効く。したがって該当曜日（alpaca=日曜、ctftime=月曜）に bot を再起動すると、**起動直後に 1 回 + 指定時刻に 1 回**通知が飛ぶ。

同じコードベース内の ctf_team は `start_notified_at_unix` を DB に永続化して送信済み管理しており（良い設計）、週次通知だけ冪等ガードが無いのは非対称。

**改善案**（いずれか、両方ならより堅牢）:
- デコレータで `tasks.loop(time=...)` を直接使えるよう、時刻設定を `__init__` で行う（`self.weekly_solve_report.change_interval(time=...)` を `.start()` の**前**に呼ぶ）
- 最終送信日を DB に永続化し、同日 2 回目をスキップする

### 5. [Medium] 認可設計が不在 — リソース作成系コマンドが全メンバーに開放

**場所**: `cog.py:83` (`/ctfteam open`), `times.py:24-28` (`/times create`), `alpacahack.py:286-324` (`/alpaca add|del`)

権限チェックがあるのは `/ctfteam close|archive` の「作成者 or manage_guild」のみ（`cog.py:560-564`）。それ以外は:

- `/ctfteam open` — 誰でもロール + チャンネル 2 個を作成できる（上限は 1 人 5 募集）
- `/times create` — 誰でも**個数無制限**にチャンネルを作成できる（カンマ区切りに上限が無く、大量指定で rate limit 直撃も可能）
- `/alpaca add|del` — 誰でも他人の登録を削除できる

信頼されたメンバーだけのサーバーなら「全開放」も妥当な設計だが、現状**どこにもその判断が書かれていない**。design.md の設計判断としては空白。

**改善案**: design.md に認可ポリシー（例:「サーバーは招待制で全メンバーを信頼するため、破壊的でないコマンドは開放する」）を 1 節書く。最低限 `/times create` には 1 回あたりの作成数上限（例: 10）を入れる。

### 6. [Low〜Medium] 募集作成のクラッシュ窓 — 孤児 Discord リソースの扱いが未定義

**場所**: `cog.py:145-236` (`handle_create_submit`)

Discord リソース作成（role → discussion → voice → 募集メッセージ）→ DB insert の順なので、**DB insert 前にプロセスが落ちると孤児リソースが残り、DB に記録が無いため自動回収不能**。ConflictError / ServiceError / 汎用例外での `cleanup_resources` 補償は良くできているが、クラッシュだけは守れない。

小規模 bot として「稀な孤児は手動掃除」で十分許容できるトレードオフ。**問題は選択自体ではなく、design.md に書かれていないこと**。「Discord 先行・DB 後行。例外は補償削除、クラッシュ時の孤児は手動対応」と 2 行明記すれば十分。

### 7. [Low] Discord リソースの参照方法が feature 間で不統一（ID vs ハードコード名）

**場所**: `cog.py:20,149-153` (`#role` チャンネルを名前で検索), `times.py:18` (`times` カテゴリを名前で検索), 一方 ctf_team カテゴリ・archive カテゴリは env の ID

名前ベースの解決はチャンネル/カテゴリのリネームで**静かに壊れる**（エラーは出るが、なぜ壊れたか運用者に分かりにくい）。ctf_team カテゴリを ID で引いているのと同じ方式に揃え、`ROLE_ANNOUNCE_CHANNEL_ID` / `TIMES_CATEGORY_ID` を env に追加するのが一貫する。

### 8. [Low] BotRuntime / get_runtime が app.py 在住のため、helpers が型安全性を失っている

**場所**: `app.py:18-28`, `helpers.py:80-82` (`log_audit`)

feature は `from bot.app import get_runtime` でアプリ全体（CTFBot クラス、signal 処理まで）に依存している。また helpers.py は app.py を import すると循環になるため、`log_audit` が `getattr(bot, "runtime", ...)` の getattr チェーンで型を捨てて回避している。

**改善案**: `BotRuntime` と `get_runtime` を `bot/runtime.py` に切り出す。feature は runtime.py のみに依存し、helpers.py も型付きでアクセスできる。1 ファイル追加・import 書き換えだけの低コストで、依存グラフが「feature → runtime ← app」に整理される。

### 9. [Low] DB 境界の型が不統一

**場所**: `db.py:292-303` (`list_campaigns(status: str | None)`) vs `db.py:225-232` (`find_campaign_by_name(status: CampaignStatus)`)

同じ Database クラス内で status の型が str と enum に割れている。cog 側（`cog.py:253`）が `"all"` を None に潰す変換をしているためだが、`CampaignStatus | None` に統一すれば typo が型エラーで捕まる。

### 10. [Low] テスト戦略の空白 — 分割基準は満たしているのにテストされていない純粋関数がある

**場所**: `discord_ops.py` の `normalize_channel_name` / `pick_unique_channel_name` / `_chunk_mentions` / `build_recruitment_message`

設計方針「Discord のモック無しでテストしたいか」で campaign.py を分離した一方、discord_ops.py 内の**実質純粋な文字列関数群**（境界値が多い: 100 文字切り詰め、サフィックス連番、1700 文字チャンク分割）が未テスト。また指摘 1 の close/archive ライフサイクルの冪等性は、現行のテスト構成では原理的に検出できない領域にある。

**改善案**: 純粋関数のテストを追加（discord.Role 等を要求しない関数はそのまま書ける）。ライフサイクルの冪等性は「`mark_message_closed` が NotFound で True を返す」のような関数単位のテストに落とせば mock 最小で書ける。

### 11. [Info] 冗長インデックス

`db.py:38-39` の `idx_campaign_guild_message (guild_id, channel_id, message_id, status)` は `UNIQUE (guild_id, message_id)` とほぼ重複。`find_active_campaign_by_message` は UNIQUE 制約の索引で十分捌ける規模。実害なし、次にスキーマを触る機会に整理でよい。

---

## 良い点（維持すべき設計）

- **設計判断が理由付きで文書化され、AST テストで機械検証されている**。「なぜ 1 ファイルか」「なぜ同期 HTTP か」が残っているため、レビューが「宣言との差分検出」で済む。この体制自体がこのリポジトリ最大の資産
- **例外階層と処理方針の対応表**（design.md）。ServiceError の catch 1 パターン統一は cog のコードを実際に単純にしている
- **同名 active 募集の TOCTOU を partial unique index（`idx_campaign_active_name_unique`）+ IntegrityError → ConflictError で DB 制約として防いでいる**。アプリ層チェックだけに頼っていない
- **募集作成失敗時の補償削除**（`cleanup_resources`）と ConflictError 時の巻き戻し
- **fail-fast の徹底**: 設定不備・extension ロード失敗・スキーマ不一致はすべて起動拒否
- **ctf_team の start 通知は `start_notified_at_unix` で永続化された冪等ガードを持つ**（指摘 4 はこのパターンを週次通知にも広げるだけ）
- `sanitize_audit_text` のメンション無害化、`AllowedMentions.none()` など出力面の防御

## 推奨アクション（優先順）

| # | 内容 | 規模 |
|---|---|---|
| 1 | close フローの冪等化（NotFound=成功、snapshot を状態遷移後に移動） | 1 ファイル修正 + テスト |
| 2 | スキーマ migration 方式の設計決定（コード or 手順書） | 設計判断 → 小実装 |
| 3 | design.md 依存ルールに db.py → models.py を明記 + models.py の arch テスト追加 | ドキュメント + テスト |
| 4 | 週次通知の再起動二重送信対策 | 2 ファイル小修正 |
| 5 | 認可ポリシーの明文化 + `/times create` 個数上限 | ドキュメント + 小修正 |
| 6-11 | 上記 Low 項目 | 随時 |

指摘 1・4 は 1 ファイル規模なので CLAUDE.md の基準では Claude 直接実装、指摘 2 は設計 → Codex 実装の対象。
