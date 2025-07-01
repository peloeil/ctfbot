# CTF Bot (Rust Version)

このリポジトリは、CTF関連の情報を提供するDiscordボットのRust実装です。

## 機能

### General Commands

*   `/echo <message>`: 指定されたメッセージを返します。
*   `/pin <message_link>`: 指定されたメッセージをピン留めします。
*   `/unpin <message_link>`: 指定されたメッセージのピン留めを解除します。

### AlpacaHack Commands

*   `/add_alpaca <name>`: AlpacaHackユーザーを追跡リストに追加します。
*   `/del_alpaca <name>`: AlpacaHackユーザーを追跡リストから削除します。
*   `/show_alpaca`: 追跡中の全てのAlpacaHackユーザーを表示します。
*   `/show_alpaca_score`: 追跡中のAlpacaHackユーザーのスコアを表示します。

### CTFtime Commands

*   `/ctf`: 今後2週間のCTFtimeイベントを表示します。

### Other Commands

*   `/help`: このヘルプメッセージを表示します。

## 開発

### 前提条件

*   Rust (stable)
*   Cargo

### ビルド

```bash
cargo build
```

### 実行

```bash
cargo run
```

## 環境変数

`.env`ファイルに以下の環境変数を設定してください。

*   `DISCORD_TOKEN`: Discord Botのトークン
*   `CTFTIME_API_KEY`: CTFtime APIのキー (必要な場合)
*   `ALPACAHACK_API_KEY`: AlpacaHack APIのキー (必要な場合)
