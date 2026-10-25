# 開発ガイド

Claude が設計し、Codex が実装する。担当や進め方が依頼で指定された場合はそちらを優先する。

## 文書の使い方

依頼で指定された仕様を優先する。それ以外の文書は既存機能の意図を調べる参考資料であり、新しい依頼を制限しない。文書と実装に差があれば、依頼・関連テスト・変更履歴から意図を確認する。

- セットアップと文書一覧: [README.md](README.md)
- モジュール分割や依存関係を変えるとき: [設計判断](docs/design.md)
- 設定・永続化を変えるとき: [データ・設定契約](docs/data-contracts.md)
- 応答・通知を変えるとき: [共通挙動](docs/core.md) と対象の [機能仕様](README.md#機能)

文書には振る舞い・制約・判断理由を残し、型宣言・SQL・設定ファイルの全文は実物を参照する。仕様変更時は対応する文書も同じ変更で更新する。

## プロジェクト固有の制約

- 単一 guild 運用。コマンド登録先は `GUILD_ID`。
- feature 間の相互 import を禁止する。`db.py` が feature から import できるのは `models.py` のみ。`db.py`・feature の `models.py`・`ctfteam/campaign.py`・`alpacahack/service.py`・`tts/service.py`・`tts/voicevox.py` は Discord 非依存とし、`ctfteam/discord_ops.py` は DB 非依存とする。[静的検証](tests/test_architecture.py)で確認する。
- 全 SQL は `db.py` の `Database` に集約する。`BotRuntime` は Settings と Database のみ保持し、外部 API クライアントは各 cog で生成する。
- async 処理からの同期 DB・HTTP 呼び出しは `asyncio.to_thread` に委譲する。
- 状態を持つ定期処理では DB の更新を確定してから通知する。削除・終了処理の `discord.NotFound` は成功扱いにする。送信失敗で状態を巻き戻さない。
- `create_bot` の `extra_extensions` / `message_content` は下流プロジェクトの拡張口。リポジトリ内の利用がなくても維持する。

## 書き方

コードは英語、Discord に送る文面は日本語。内部例外や外部データ欠落時の代替値は例外とする。dataclass は `frozen=True, slots=True` を標準とする。複数段の業務検証は `ServiceError` を送出して cog で応答に変換する。

コードで処理を表し、テストで振る舞いを検証する。コミット本文には問題と変更理由、コメントには素直な実装を避けた理由を書く。lint・型チェックの設定は [pyproject.toml](pyproject.toml) を参照する。

## 検証

`uv sync` で開発環境を用意する。コード変更では以下を通す。文書のみの変更ではリンク・参照・記載内容を確認し、コードの検査を毎回繰り返す必要はない。

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run ty check
uv run -m unittest discover -s tests -q
```

ローカルテストは一時 DB とモックを使う。変更に起因する失敗の修正と再検証まで進める。bot は起動しない。実際の Discord 動作確認は人間が行う。
