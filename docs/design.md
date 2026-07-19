# 設計判断

このドキュメントはプロジェクトの設計思想と技術選定の理由を記録する。

## 記述規則

docs/ 配下の文書は AI が実装の正本として読む。各記述は「必須契約 / 意図的な非目標 / 設計理由 / 例示」のいずれかとして書き、次を守る。

- 要求形で書く。「現在〜になっている」「既に〜がある」等の時間依存・実装依存の記述をしない
- 実装ファイルを正本として参照しない（正本は常に docs/ 側。どの文書が何の正本かは CLAUDE.md・AGENTS.md の参照表による）
- 数値・文字列の定義は正本の 1 箇所にだけ書き、他所からは参照する。ユーザー向けメッセージは完全な文字列で記載する
- アーキテクチャ制約・コーディング規約の規範文言の正本は `AGENTS.md`。本書は同じ制約の理由と適用基準を記す（乖離時は AGENTS.md が正）

## 前提: 単一 guild 運用

この bot は 1 つの Discord トークンと 1 つの bot アプリケーションを、ただ 1 つの guild（`GUILD_ID`）に対して運用する。

- guild 内リソース（カテゴリ・チャンネル・ロール）を指す設定はグローバルに 1 つずつ持つ（guild ごとの設定表を持たない）
- スラッシュコマンドは `GUILD_ID` の guild にのみ登録する（グローバル登録しない）。反映が即時になり、DM にコマンドが露出しない
- 複数 guild への招待は想定外とし、`GUILD_ID` 以外の guild での挙動は未定義（前提を検証する防御コードを追加しない。非目標）
- `require_guild` は登録方式により通常到達しない防御的境界として維持する（`interaction.guild` の型が Optional であるため、narrowing を兼ねる）
- アプリ状態のテーブルは guild 次元を持たない。Discord イベントの記録は発生イベントの属性として `guild_id` を保持する

## 分割方針

### 読むべきファイルを名前だけで特定できるようにする

この規模（数千行・十数ファイル）のコードベースでは、人間と AI のどちらにとっても最も高コストな操作は「ファイルの内容を読むこと」ではなく「どのファイルを読むべきかを判断すること」である。分割の妥当性は次の問いで検証する: **任意のバグ報告や機能追加に対して、AGENTS.md の制約表とファイル名・関数名だけを見て、読むべきファイルの集合を正しく特定できるか。** この特定を困難にする変更は、可読性の改善ではなく劣化である。

この基準から導かれる優先順位:

- **ファイル数を安易に増やさない。** ファイルを追加するたびに「どれを読むか」の選択肢が増える。責務の分離はまず既存ファイル内の関数分割と命名で表現する
- **ファイル名と関数名で配置先を予測可能にする。** 「入力パースの問題 → `parse_*`」「Discord リソース解決の失敗 → `require_*`」のように、症状から関数が引けること。1 つの関数が複数の責務（例: parse と DB 依存の可否確認）を持つと、この予測が崩れる
- **型シグネチャで読まなくてよいファイルを増やす。** `def close(campaign: ActiveCampaign)` という型を見れば、呼び出し側で narrowing 済みであることが関数本体を開かずに分かる
- **抽出は呼び出し側で自己文書化される場合のみ行う。** `require_guild(interaction)` と書くだけで「guild context が確立された」と読める場合は抽出してよい。内部に非自明な副作用がある関数を同じパターンで抽出すると、本体を読まないと安全に変更できなくなり、抽出の利点が失われる

### 型の境界でモジュールを分割する

Discord 非依存ロジックを独立してテスト・再利用する必要がある場合は別モジュールに分ける。単一ファイルで完結する小規模 feature では同居してよい。分割の判断基準は行数ではなく「Discord のモック無しでテストしたいか」「他の feature から再利用するか」。ただし feature 間の相互 import は禁止のため、feature をまたいで再利用するロジックは昇格させる: Discord 依存なら `helpers.py`、DB 操作なら `db.py`。どちらにも依存しない共有ロジックが必要になった場合は、`errors.py`・`log.py` と同列のコア層モジュールとして追加する。

### `discord_ops.py` を ctf_team cog から分離する

Discord リソース操作（チャンネル作成、権限設定、archive 移動など）を standalone 関数に切り出す。関数シグネチャが依存を型で明示するため、暗黙の `self` 参照が発生しない。変更時に影響範囲が関数単位で閉じる。

## 依存ルール

```
bot パッケージ内部の依存のみ示す（discord・標準ライブラリ・外部ライブラリは省略）。
✗ は import 禁止の制約。

ctf_team/cog.py          → ctf_team/campaign.py, ctf_team/discord_ops.py, ctf_team/models.py, helpers.py, runtime.py
ctf_team/campaign.py     → db.py, ctf_team/models.py
ctf_team/campaign.py     ✗ discord（import 禁止）
ctf_team/discord_ops.py  → helpers.py, ctf_team/models.py
ctf_team/discord_ops.py  ✗ db.py（import 禁止）
sudo/cog.py              → sudo/models.py, helpers.py, runtime.py
alpacahack.py            → db.py, helpers.py, runtime.py
ctftime.py               → helpers.py, runtime.py
times.py                 → helpers.py, runtime.py
utility.py               → （bot 内部依存なし）
audit_log.py             → runtime.py
db.py                    → features/<feature>/models.py（許可。ただし models.py は discord import 禁止）
db.py                    ✗ discord（import 禁止）
helpers.py               → runtime.py
runtime.py               → config.py, db.py

errors.py と log.py はどの層から import してもよい（図からは省略）。
feature 間の相互 import は禁止（features/ 直下のすべての feature が対象）。
```

この依存図は許可される依存の上限であり、新しい依存辺の追加は設計判断としてレビューを要する。なお `utility.py` は bot 内部依存を持たないため、`send_interaction` を使わず直接 `interaction.response` で応答する（コマンド応答経路の明示的な例外。`docs/core.md`）。

`tests/test_architecture.py` が AST で静的に検証するのは ✗ の禁止制約・db.py の feature import が models のみであること・feature 間の相互 import 禁止で、→ の依存関係はレビューでのみ担保される。新 feature 追加時は同テストの `feature_modules` 一覧への追加が必要（手順は `AGENTS.md`）。

コア層の db.py が feature の models.py に依存するのは「Database を 1 クラスに集約する」方針の意図的な帰結。この依存を安全に保つため、feature の models.py は discord に依存しない純粋なデータモデルに限定する。

## 技術選定

### Python 3.14+

`pyproject.toml` の `requires-python = ">=3.14"` に準拠。

### discord.py 2.x

`commands.Bot` + `app_commands` でスラッシュコマンドを実装する。`command_prefix=commands.when_mentioned` でテキストコマンドは実質無効。`Intents.members = True` を有効にして `on_raw_reaction_add` でメンバー取得を行う。

### SQLite（WAL mode）

単一プロセスの bot で十分な規模。WAL mode で読み取りの並行性を確保する。イベントループ上の blocking I/O は `asyncio.to_thread` 経由（適用範囲の正本は AGENTS.md 制約 10）。

スキーマ変更は `_MIGRATIONS`（`{from_version: SQL スクリプト}`）に version N → N+1 の移行 SQL を登録する方式。起動時の検証・移行手続き・拒否条件（バージョン管理外の DB・bot より新しい version・移行パスの無い version はいずれも起動拒否 = fail-fast）の契約は `docs/data-contracts.md`「起動時のスキーマ検証・移行手続き」を正本とする。移行スクリプトは再実行に耐える形で書く — スクリプト適用と version 更新は atomic でなく、間にクラッシュすると再実行されるため。

### requests（同期 HTTP）

外部 API 呼び出しは `asyncio.to_thread` で包むため、同期ライブラリで十分。aiohttp の複雑さを避ける。

### BeautifulSoup4

AlpacaHack のスクレイピング用。HTML パーサーとして `html.parser` を使用。

### uv

パッケージ管理・仮想環境管理。`uv sync --group dev` で開発依存を含むインストール。

## アーキテクチャ判断

### validation は例外ベース

複数ステップの検証は `ServiceError` を raise し、cog で `try/except ServiceError` の 1 パターンで統一する。新しいバリデーション項目追加時も `raise ServiceError("...")` を書くだけで呼び出し側の変更が不要。単純な Discord 入力チェック（空文字・guild 存在確認など）は cog 内で直接応答してよい。

### validation は境界ごとに分ける

入力検証を 1 関数に集約せず、依存する境界ごとに責務を分ける。

1. **raw input の parse** — 文字列の正規化、構文解析、値同士の整合性を確認し、純粋なデータモデルへ変換する。DB や Discord に依存させない
2. **business rule の確認** — DB の現在状態に依存する上限、重複、遷移可否などを確認する。同期 DB アクセスを含むため cog からは `asyncio.to_thread` で呼ぶ
3. **外部オブジェクトの narrowing** — nullable な Discord オブジェクトや種別不明の channel を `require_*` 関数で具体型へ絞り込む。失敗時は `ServiceError` を raise する
4. **orchestration** — cog は上記の結果を受け取り、外部副作用の実行順序と補償処理だけを担当する

純粋な parse と DB 依存 rule を分けることで、入力形式のテストに DB fixture が不要になり、DB rule のテストでは既に正規化済みの値だけを扱える。外部オブジェクトの存在確認と型確認を boundary 関数へ閉じ込めることで、後続処理では `None` や誤った Discord channel 型を繰り返し確認しない。

新しい処理を追加するときは、次の基準で配置する。

| 処理 | 配置 |
|---|---|
| 空白除去、日時 parse、値同士の大小比較 | Discord 非依存の parse 関数 |
| DB 件数、重複、現在状態に基づく可否 | service / business rule 関数 |
| guild、channel、role などの存在・具体型確認 | Discord boundary 関数 |
| Discord リソース作成、DB 保存、通知の順序制御 | cog |

境界関数の名前は接頭辞で契約を表す。

| 接頭辞 | 契約 |
|---|---|
| `parse_*` | raw value を構文解析・正規化し、失敗時は定義済み例外を raise する |
| `require_*` | 必須の外部オブジェクトを解決し、存在しないか型が違えば例外を raise する |
| `find_*` | 見つからないことが正常な結果であり、戻り値に `None` を含む |
| `resolve_*` | cache/fetch など複数経路で取得を試み、取得不能を戻り値か仕様化された例外で表す |
| `ensure_*` | 値の変換ではなく、現在の状態に対するビジネス上の事前条件を確認する |

`validate_*` は「何を返すか」「失敗が通常結果か例外か」が名前から読めないため、新規関数では使わない。

一方、次の分岐は関数へ抽出せずインラインを維持する。

- **業務上の判断そのもの**（権限確認、競合後の補償、冪等判定、空一覧の表示方法）— 処理の意味であり、隠すと主要フローが読めなくなる
- **1 行で結果が明白なチェック** — `validate_campaigns_exist()` のような名前に置き換えると、通常の表示分岐が入力不正のように見える
- **1 箇所でしか使わず、domain invariant も確立しないチェック** — 型または名前による情報圧縮がなく、読むファイルが増えるだけ

### 状態依存データは型で表す

status などの discriminator によって必須 field や利用可能な field が変わる場合、全状態を nullable field の多い 1 dataclass に詰め込まない。状態ごとの `frozen=True, slots=True` dataclass と `Literal` discriminator を定義し、union type alias でまとめる。

```python
@dataclass(frozen=True, slots=True)
class ActiveItem:
    status: Literal[ItemStatus.ACTIVE]
    started_at: int


@dataclass(frozen=True, slots=True)
class ClosedItem:
    status: Literal[ItemStatus.CLOSED]
    started_at: int
    closed_at: int


type Item = ActiveItem | ClosedItem
```

このパターンは、次の条件を満たす場合に使う。

- discriminator ごとに「存在してはならない field」または「必須になる field」がある
- status 固有処理で nullable check や `assert` が繰り返される
- query 自体が特定 status の行だけを返す

DB decoder は信頼境界として discriminator と nullable column の整合性を実行時に検証し、不正な行は `RepositoryError` にする。status 固有 query は対応する具体型を返し、複数 status を返す query だけが union を返す。呼び出し側で状態固有 field にアクセスするときは `isinstance` で型を絞り込み、検証を伴わない `cast` や `assert` で型検査を回避しない。

この設計により、不正な状態を decoder より内側へ持ち込まず、status 固有 field の利用可否を型検査で保証できる。

### sentinel は入口で正規化する

未設定を表す `0`、空文字、特殊文字列などの sentinel は、Settings 構築、DB decoder、外部 API decoder といった入口で canonical representation に変換する。内部モデルでは未設定を原則 `None` で表し、型も `T | None` にする。

```python
optional_channel_id = _read_int(..., default=0) or None
```

境界より内側では sentinel の元表現を扱わない。

- optional ID は `is None` / `is not None` で分岐する
- `optional_id or 0` で外部 API に渡さない
- `optional_id <= 0` や `if optional_id` で未設定判定をしない
- 必須 ID は `int` のままにし、Settings 構築時に正数を検証する
- DB の nullable ID column は decoder で `0` も `None` に正規化する

これにより、同じ「未設定」が `0` と `None` の 2 通りで内部を流れることを防ぎ、型 narrowing と実行時判定を一致させる。

### 設定値の検証契約

環境変数は `load_settings` が起動時に検証し、違反は `ConfigurationError` で fail-fast する。変数一覧・型・デフォルト・読み取り規則の正本は `docs/data-contracts.md`「設定契約」。環境変数を追加・変更するときは同表を更新し、この契約に合わせる。

### 境界変更のテスト方針

境界を追加・変更した場合は、各層を独立して検証する。

- parse: 正規化後の値と不正 raw input の拒否
- business rule: DB 状態ごとの許可・拒否
- external boundary: 正しい具体型の返却、不在、誤った型
- decoder: 各 discriminator の正常 decode と、field 整合性違反の拒否
- sentinel normalization: 未設定・sentinel・正常値が canonical representation になること

テスト名は境界の内部実装ではなく、保証する振る舞いを記述する。

### Database を 1 クラスに集約する

全テーブル・全 SQL が `db.py` の 1 ファイルに集まるため、新しいクエリの追加先に迷わない。

### BotRuntime は Settings + Database のみ持つ

API クライアントは各 cog の `__init__` でローカル生成する。feature 追加時に runtime の変更が不要。

`BotRuntime` / `get_runtime` は `runtime.py` に置く（app.py ではなく）。feature と helpers が bot アプリ全体（CTFBot クラス、signal 処理）に依存せず、runtime だけに依存できる。helpers.log_audit も型安全に runtime へアクセスできる。

### 定期ループから呼ばれる処理は冪等にする

毎分ループ（close/archive 等）は失敗した項目を翌分また拾う。したがって:

- **非冪等な副作用（通知・スナップショット送信）は、DB の状態遷移が確定した後に置く。** 状態遷移前に置くと、後続ステップの恒久的失敗時に毎分再送される
- **対象が既に存在しない（`discord.NotFound`）操作は成功扱いにする。** 「消すべきものが既に無い」「編集すべきメッセージが既に無い」は目的達成と同義
- 通知送信自体の失敗は状態を巻き戻さない（DB が正）

ループの共通契約:

- ループ本体はイテレーション全体を `except Exception` で捕捉してログし、ループを停止させない
- `before_loop` で bot の ready を待つ
- cog unload 時にループを cancel する

通知の配信保証は全て **at-most-once** とする: claim（状態遷移の確定）に成功した呼び出しだけが送信を試み、送信失敗はログに残して再送しない。at-least-once 化・再送機構の導入は非目標。

### 週次通知の実行時刻は start 前に設定する

`tasks.loop` は相対間隔（`hours=` 等）だと最初のイテレーションを即時実行する。`change_interval(time=...)` は次イテレーションからしか効かないため、`before_loop` 内で呼ぶと bot 再起動時に即時 1 回 + 指定時刻に 1 回の二重実行になる。時刻指定は cog の `__init__` で `.start()` より前に `change_interval(time=...)` を呼んで行う。

### 認可ポリシー

このボットは招待制の信頼されたメンバーのみのサーバーで運用する前提のため、コマンドは原則全メンバーに開放する。例外:

- `/ctfteam close|archive` — 作成者 または `manage_guild` 権限保持者のみ（他人の募集を壊せないように）
- `/sudo` — sudoer ロール保持者のみ。管理者昇格はサーバー破壊につながるため fail-closed に倒す（詳細は `docs/features/sudo.md`）
- リソース量の暴走は、各 feature 仕様で定めるコマンド側の上限で防ぐ

### 募集作成は Discord 先行・DB 後行

`/ctfteam open` は Discord リソース（ロール・チャンネル・メッセージ）を作成してから DB に記録する。例外時は `cleanup_resources` で補償削除する。DB insert 前のプロセスクラッシュ時、および補償削除自体の失敗時（リソースごとに warning ログを記録して継続する）は孤児リソースが残り自動回収されない。発生頻度が低いため、warning ログで検知して手動掃除で許容する。

### 例外階層

| 例外 | 用途 | 処理 |
|---|---|---|
| `ServiceError` | ユーザー向けエラー。メッセージは日本語 | cog が catch → `send_interaction` で表示 |
| `RepositoryError` | DB 操作失敗 | ログに記録 |
| `ConflictError` | 一意制約違反（同名 campaign 等） | cog が catch → cleanup + エラー表示 |
| `ExternalAPIError` | 外部 API 呼び出し失敗 | ログに記録 + ユーザーにフォールバック応答 |
| `ConfigurationError` | 起動時の設定不備 | fail-fast（bot 起動しない） |

`ExternalAPIError` は `ServiceError` の派生であるため、外部 API を呼ぶ cog は `except ExternalAPIError` を `except ServiceError` より**先に**置く。`ExternalAPIError` のメッセージはログ用の内部文字列であり、ユーザーへそのまま表示せず、各 feature が定義するフォールバック文言を表示する（内部文字列は「ユーザー向けメッセージは日本語」規約の対象外）。
