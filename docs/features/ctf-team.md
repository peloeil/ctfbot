# CTF 募集管理 (ctf_team)

## 概要

`/ctfteam` コマンドグループで CTF 参加者の募集を管理する。募集の作成・一覧・終了・アーカイブのライフサイクルを持つ。

## ファイル構成

| ファイル | 責務 |
|---|---|
| `models.py` | `ActiveCampaign`, `ClosedCampaign`, `Campaign`（union alias）, `CampaignDraft`, `CampaignStatus` データモデル |
| `campaign.py` | 入力パース（`parse_campaign_draft`）・事前条件確認（`ensure_campaign_can_be_created`）・ビジネスロジック（Discord 非依存） |
| `discord_ops.py` | Discord リソース操作（チャンネル・ロール・メッセージ）、boundary 関数（`require_category`, `require_role_channel`） |
| `cog.py` | スラッシュコマンド定義・イベントリスナー・バックグラウンドタスク |

## ライフサイクル

```
active ──(end_at_unix 到達 or /ctfteam close)──→ closed ──(archive_at_unix 到達 or /ctfteam archive)──→ archived
```

### active 状態

- 募集メッセージが `#role` チャンネルに投稿されている
- リアクション (✅) でロール付与が行われる
- discussion / voice チャンネルが存在する

### closed 状態

- 募集メッセージに `🔒 **この募集は終了しました。**` ヘッダーが追加される
- voice チャンネルは削除される
- discussion チャンネルに参加メンバースナップショットが投稿される
- `archive_at_unix = closed_at + 30日` が設定される

#### close 処理の順序（冪等性保証）

close は毎分ループからリトライされるため、以下の順序で行う:

1. 募集メッセージへのヘッダー追加（冪等: ヘッダー既存なら何もしない。メッセージが `NotFound` なら成功扱い）
2. voice チャンネル削除（冪等: `NotFound` は成功扱い）
3. 1・2 のいずれかが失敗したら中断（DB は active のまま。翌分リトライ）
4. DB を closed に更新
5. **4 で実際に active → closed へ遷移した場合のみ**、discussion チャンネルへスナップショットを送信

スナップショット送信を状態遷移後に置くことで、リトライ時の重複送信を防ぐ。スナップショット送信自体の失敗は close を巻き戻さない。

### archived 状態

- discussion チャンネルが archive カテゴリに移動される
- チャンネルは読み取り専用になる（全員閲覧可、送信不可）
- ロールが削除される

## コマンド

### `/ctfteam open ctf_name [role_color]`

1. Modal が開く（開始日時・終了日時を入力）
2. 入力パース（`campaign.parse_campaign_draft`）→ 作成可否確認（`campaign.ensure_campaign_can_be_created`）
3. ロール作成 → discussion チャンネル作成 → voice チャンネル作成 → 募集メッセージ送信 → ✅ リアクション追加
4. DB に campaign レコード作成
5. 作成者にロール付与
6. 開始時刻が既に過ぎていれば即座に開始通知

失敗時は作成済みリソースをロールバック（`discord_ops.cleanup_resources`）。

バリデーションルール:
- CTF 名: 空白正規化、1〜60文字
- 終了日時: 省略可（常設）。指定する場合は開始日時より後
- 同一ユーザーの active 募集上限: 5件
- 同名の active 募集は不可（大文字小文字無視）

### `/ctfteam list [status]`

status: `active`（デフォルト）, `closed`, `all`

Embed 形式で一覧表示。各 campaign について状態・開始/終了日時・募集メッセージリンク・discussion/VC チャンネル・ロール・作成者を表示。description 4096 文字上限で打ち切り。

### `/ctfteam close ctf_name`

権限: 作成者 または `manage_guild` 権限保持者。

### `/ctfteam archive ctf_name`

権限: close と同じ。

archive 対象が見つからない場合のエラーメッセージ:
- active で存在 → 「先に `/ctfteam close` で終了してください。」
- 既に archived → 「既に archive 済みです。」
- 不在 → 「募集が見つかりません。」

## リアクションハンドラ

`on_raw_reaction_add` で ✅ リアクションを監視。

- bot 自身のリアクションは無視
- 対象メッセージが active campaign でなければ無視
- campaign が期限切れの場合は自動 close（audit ログ省略）
- メンバーにロールを付与し、discussion チャンネルに参加通知を投稿

## バックグラウンドタスク（1分間隔）

| タスク | 内容 |
|---|---|
| `start_due_campaigns` | `start_at_unix` が到達した campaign の discussion に開始通知を投稿 |
| `close_expired_campaigns` | `end_at_unix` が到達した active campaign を自動 close |
| `archive_closed_campaigns` | `archive_at_unix` が到達した closed campaign を自動 archive |

## Discord リソース操作 (discord_ops.py)

### チャンネル名の正規化

`normalize_channel_name`: lowercase → スペースを `-` に → `[^a-z0-9\-]` を `-` に置換 → 連続 `-` を 1 つに → 先頭末尾 `-` 除去 → 100文字で切る（times の正規化と同一ルール）。

`pick_unique_channel_name`: カテゴリ内で重複する場合 `base-2`, `base-3` ... を試す。

### チャンネル権限

**discussion チャンネル:**
- `@everyone`: `view_channel=False`
- ロール: `view_channel=True`, `send_messages=True`, `read_message_history=True`
- 作成者: 同上
- bot: 同上 + `manage_channels=True`

**voice チャンネル:**
- `@everyone`: `view_channel=False`
- ロール: `view_channel=True`, `connect=True`, `speak=True`, `stream=True`
- 作成者 / bot: 同上

### archive 後の権限

- `@everyone`: `view_channel=True`, `send_messages=False`, `add_reactions=False`, `create_public_threads=False`, `create_private_threads=False`, `read_message_history=True`
- ロールの overwrite は削除

### 募集メッセージ形式

```
📣 **{ctf_name}** 参加者募集

🕐 開始: <t:{start}:f> (<t:{start}:R>)
🏁 終了: <t:{end}:f> (<t:{end}:R>)   ← None なら "常設"
💬 CTFチャンネル: #discussion
👥 ロール: @role

✅ リアクションを付けると @role ロールを付与します。
```

### メンション分割

`MENTION_CHUNK_SIZE = 1700` 文字ごとに分割して複数メッセージで送信。Discord の 2000 文字制限にマージンを持たせている。

## データモデル

### CampaignStatus

`ACTIVE = "active"`, `CLOSED = "closed"`

### ActiveCampaign

```python
@dataclass(frozen=True, slots=True)
class ActiveCampaign:
    id: int
    guild_id: int
    channel_id: int          # 募集メッセージのチャンネル
    message_id: int          # 募集メッセージ
    role_id: int
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None  # None = 常設
    status: Literal[CampaignStatus.ACTIVE]
    created_by: int
    created_at_unix: int
    start_notified_at_unix: int | None = None
    discussion_channel_id: int | None = None
    voice_channel_id: int | None = None
```

### ClosedCampaign

```python
@dataclass(frozen=True, slots=True)
class ClosedCampaign:
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    role_id: int
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
    status: Literal[CampaignStatus.CLOSED]
    created_by: int
    created_at_unix: int
    closed_at_unix: int
    archive_at_unix: int
    archived_at_unix: int | None = None
    discussion_channel_id: int | None = None
    voice_channel_id: int | None = None
```

### Campaign

```python
type Campaign = ActiveCampaign | ClosedCampaign
```

DB decoder は status と nullable field の整合性を実行時に検証する。active 固有の query は `ActiveCampaign` を、closed 固有の query は `ClosedCampaign` を返す。

### CampaignDraft

```python
@dataclass(frozen=True, slots=True)
class CampaignDraft:
    ctf_name: str
    start_at_unix: int
    end_at_unix: int | None
```

## DB スキーマ

```sql
CREATE TABLE IF NOT EXISTS ctf_team_campaign (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    ctf_name TEXT NOT NULL COLLATE NOCASE,
    start_at_unix INTEGER NOT NULL,
    end_at_unix INTEGER,
    status TEXT NOT NULL CHECK (status IN ('active', 'closed')),
    created_by INTEGER NOT NULL,
    created_at_unix INTEGER NOT NULL,
    closed_at_unix INTEGER,
    discussion_channel_id INTEGER,
    archive_at_unix INTEGER,
    archived_at_unix INTEGER,
    start_notified_at_unix INTEGER,
    voice_channel_id INTEGER,
    UNIQUE (guild_id, message_id)
);
```

`ctf_name` は `COLLATE NOCASE` で大文字小文字無視。`(guild_id, ctf_name)` に partial unique index（`WHERE status = 'active'`）で同名 active 重複を防ぐ。

## 定数

| 定数 | 値 | 説明 |
|---|---|---|
| `MAX_ACTIVE_PER_USER` | 5 | 同一ユーザーの active 募集上限 |
| `MAX_CTF_NAME_LENGTH` | 60 | CTF 名の最大文字数 |
| `ARCHIVE_DELAY_DAYS` | 30 | close から archive までの日数 |
| `INPUT_DATETIME_FORMAT` | `%Y-%m-%d %H:%M` | 日時入力形式 |
| `REACTION_EMOJI` | ✅ | 参加リアクション |
| `ROLE_ANNOUNCE_CHANNEL_NAME` | `role` | 募集メッセージの投稿先チャンネル名 |
