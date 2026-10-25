# CTFBot

単一の CTF コミュニティ向け Discord bot。参加者募集、CTF 情報通知、チャンネル作成、期限付き管理者ロールを扱う。

## セットアップ

Python のバージョンは [.python-version](.python-version)、依存条件は [pyproject.toml](pyproject.toml) を参照する。

```bash
uv sync
cp .env.example .env
```

`.env` に `DISCORD_TOKEN` と `GUILD_ID` を設定し、使用する機能のチャンネル・カテゴリ・ロール ID を追加する。全変数の用途・デフォルト・検証規則は [設定契約](docs/data-contracts.md#設定契約環境変数) を参照する。

Discord 側の準備が済んだら、運用者が起動する。本番用の依存同期には `uv sync --no-dev` を使う。

```bash
uv run --no-dev --locked --env-file .env -m ctfbot
```

### Discord の準備

1. Developer Portal の Installation で `Guild Install` を有効にし、`Install Link` を `None` にする。
2. OAuth2 の scope に `bot` と `applications.commands` を選択し、生成された URL から対象サーバーへ招待する。
3. Bot の公開設定をオフにし、`Server Members Intent` を有効にする。VC 読み上げを使う場合は `Message Content Intent` も有効にする（[運用](docs/features/tts.md#運用)）。
4. [必要な権限](docs/features/utility.md#必要な-bot-権限) を付与し、Bot のロールを操作対象ロールより上に置く。招待後は `/perms` で付与状態を確認できる。

CTF 募集には投稿先チャンネル・CTF 用カテゴリ・archive 先カテゴリを用意し、CTFTEAM の 3 ID をすべて設定する。times には作成先カテゴリの `TIMES_CATEGORY_ID` を設定する。sudo のロール準備は [sudo の前提](docs/features/sudo.md#discord-側の前提) を参照する。

## 機能

| 機能・仕様 | コマンド / 動作 |
|---|---|
| [CTF 募集管理](docs/features/ctf-team.md) | `/ctfteam open・list・close・archive`、リアクション参加、自動終了・archive |
| [CTFtime](docs/features/ctftime.md) | `/ctftime`、月曜のイベント通知 |
| [AlpacaHack](docs/features/alpacahack.md) | `/alpaca add・del・list・daily・solve`、Daily 問題通知、日曜の solve 集計 |
| [times](docs/features/times.md) | `/times create` |
| [ユーティリティ](docs/features/utility.md) | `/help`、`/perms`、`/roll` |
| [一時昇格](docs/features/sudo.md) | `/sudo`、`/unsudo`、期限切れロールの自動剥奪 |
| [Discord 監査ログ](docs/features/audit-log.md) | イベントを DB に保存し、管理者操作を通知 |
| [VC 読み上げ](docs/features/tts.md) | `/read join・leave・skip・stop`、VC テキストチャットの VOICEVOX 読み上げ（参加者ごとに声を割り当て）（`TTS_VOICEVOX_URL` 設定時のみ） |
| [共通挙動](docs/core.md) | コマンド実行ログ、接続・停止通知、応答とメンション制御 |

## 開発資料

| 調べたいこと | 参照先 |
|---|---|
| 開発時の制約・検証コマンド | [AGENTS.md](AGENTS.md) |
| 分割方針・設計理由 | [設計判断](docs/design.md) |
| 環境変数・モデルの不変条件・DB の保証と移行 | [データ・設定契約](docs/data-contracts.md) |
| 自動検証 | [CI](docs/ci.md) |

実装・テストは `src/ctfbot/`・`tests/` に置く。文書は変更対象に応じて参照する。
