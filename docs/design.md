# 設計判断

依存の境界や永続化の設計を変えるときに参照する。共通の制約は [AGENTS.md](../AGENTS.md)、機能ごとの振る舞いは [機能仕様](../README.md#機能) に置く。

## 運用の前提

1 つの bot アプリケーションを `GUILD_ID` の 1 guild で運用する。コマンドはその guild にのみ登録し、アプリ状態のテーブルや設定に guild ごとの区分を持たせない。監査ログの `guild_id` は発生イベントの属性として保存する。複数 guild への招待や DM コマンドは対象外。

既存メンバーの知り合いであることを確認した後、メンバーロールを手動付与する。`@everyone` の Guild 権限は `view_channel`・`read_message_history` のみにし、公開チャンネルの閲覧を許可する。投稿・VC 参加・コマンド利用などはメンバーロールで許可する。

通常コマンドの利用範囲は Discord のロール・チャンネル権限で制御する。Bot 側では、募集の終了・archive を作成者または `manage_guild` 保持者に、管理者昇格を sudoer に限定する。管理操作は昇格中（`manage_guild` 保持）に限り、例外として VC 読み上げの skip だけは sudoer ロールのままでも許す。詳細は各機能仕様を参照する。

## 分割と依存

Discord のモックなしでテストするロジックを分離する。小さい feature は単一ファイルでよく、行数や命名パターンを揃えるためだけに層を増やさない。

| 配置 | 役割 |
|---|---|
| feature の cog | コマンド・イベント・定期タスク、Discord と DB の操作順序・補償 |
| ctfteam の campaign / AlpacaHack の service | Discord 非依存の入力処理・業務ロジック |
| ctfteam の discord_ops | DB に依存しない Discord リソース操作 |
| feature の models | Database と共有する Discord 非依存の型 |
| db.py | 全テーブルの SQL とトランザクション |
| helpers.py | feature をまたぐ Discord 操作 |
| runtime.py | Settings と Database の受け渡し |

Database が feature の models に依存するのは、SQL を 1 クラスへ集約するため。runtime を app から分けるのは、feature が bot の起動・終了処理に依存せず設定と DB を受け取るため。

新しい cog の最小例は [times.py](../src/ctfbot/features/times.py)、DB・定期タスクを使う例は [alpacahack/cog.py](../src/ctfbot/features/alpacahack/cog.py)。追加時は `setup` を定義し、[DEFAULT_EXTENSIONS](../src/ctfbot/cogs_loader.py) と [アーキテクチャテスト](../tests/test_architecture.py) の `feature_modules` に登録する。

## 型とバリデーション

入力の構文解析、DB 状態に基づく可否判定、Discord オブジェクトの存在・型確認を、それぞれの依存境界で行う。cog から呼ぶ同期 DB 処理はスレッドへ委譲する。単純な空文字チェックや表示分岐は cog に置いてよい。

| 接頭辞 | 呼び出し側に伝える意味 |
|---|---|
| `parse_*` | 入力を正規化・構文解析する。不正なら例外 |
| `require_*` | 必須オブジェクトを具体型で返す。不在・型違いなら例外 |
| `find_*` | 不在も正常な結果として `None` を返す |
| `resolve_*` | cache / fetch など複数経路で解決する |
| `ensure_*` | 現在状態の業務上の事前条件を確認する |

状態ごとに必須フィールドが変わる場合は、状態別 dataclass と union で表す。DB decoder で状態と NULL の整合性を検証し、壊れた行は `RepositoryError` とする。状態限定の query は対応する具体型を返す。

optional ID の `0` は Settings・DB decoder の入口で `None` に揃える。内部では `is None` で判定し、必須 ID は正数の `int` とする。境界のテストでは正常値に加え、不正入力・不在・状態不整合を確認する。

例外階層の定義は [errors.py](../src/ctfbot/errors.py)。`ServiceError` はユーザーへ表示できる業務エラー、`RepositoryError` は DB 障害、`ConfigurationError` は起動拒否に使う。`ExternalAPIError` は `ServiceError` の派生なので先に捕捉し、内部メッセージをログへ、機能ごとの取得失敗メッセージをユーザーへ返す。

## 技術選定

- SQLite の WAL を使う。単一プロセスの運用に足り、DB 呼び出しごとの接続でスレッド間の接続共有を避けられる。
- HTTP は requests をスレッドから呼ぶ。非同期クライアントを別途導入する必要がない。
- AlpacaHack の HTML は BeautifulSoup と標準の `html.parser` で読む。
- Python・依存パッケージの条件は [pyproject.toml](../pyproject.toml)、実行環境は [.python-version](../.python-version)、固定バージョンは [uv.lock](../uv.lock) を参照する。

## 定期処理と副作用

終了・archive・剥奪は途中で失敗すると次のループが再試行する。Discord 上の削除・編集は再実行可能にし、DB の状態遷移が成功した呼び出しだけが通知する。通知自体の失敗はログに残し、状態を戻さず再送しない。状態確定と送信の間のクラッシュによる通知欠落は許容する。

対象リソースが既に消えている場合は、削除や終了の目的を達成したものとして扱う。ただし sudo のメンバー照会では、不在と API 障害を区別して剥奪記録を残す（[sudo](features/sudo.md)）。

ループは ready 後に実行し、cog unload 時に cancel する。イテレーション全体の例外をログに残して、後続の実行を継続する。

時刻指定のループは `__init__` で `change_interval(time=...)` を `start()` より先に呼ぶ。`before_loop` で切り替えると相対間隔ループの初回即時実行が残り、再起動時に二重通知される。

副作用の順序は失敗時に守りたい状態で決める。募集作成は Discord リソースを作ってから DB に記録し、保存前の失敗を補償削除する。クラッシュや補償削除の失敗で残る孤児リソースは手動回収する。sudo は剥奪対象を失わないよう DB 記録を先に確定する。具体的な順序は各機能仕様に置く。

## 文書の保守

常時読む指示はプロジェクト固有の制約と参照先に絞り、詳細は変更対象に応じて読む。実装から直接確認できる型・SQL・設定の全文や一般的な手順を文書へ複製しない。作業指示は目的・制約・完了条件を中心に書く。

この整理方針は OpenAI の [Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra) を参考にしている。
