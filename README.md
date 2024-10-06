# ctfbot

CTF 用の discord bot

# 開発準備
## 自分のサーバーへの bot の導入
自分が管理者で他の人に迷惑のかからない discord サーバー(自分のみがメンバーのサーバーなど)を用意してください。
まず Discord Developers Portal で discord bot を作成し、好きな名前をつけます。左欄の設定について、以下のように順番に設定してください。
### Installation
Install Link を None にする必要があるかもしれません(要出典)
### Bot
`cp .env.example .env` とし、`.env` 内の `user_provided` を token の実際の文字列で置き換えてください。
このファイルは絶対に commit に含めないでください。
このリポジトリは現状 private ではあるし `.gitignore` にも含めていますが、個人でも気をつけてください。

PUBLIC BOT を uncheck してください。

Privileged Gateway Intents は、現状は MESSAGE CONTENT INTENT のみ必要です。
### OAuth2
Scope は bot にしてください。

現状必要な BOT_PERMISSIONS は以下の通りです。余分な権限が含まれているのを見つけた場合は issue に報告をお願いします。
- GENERAL PERMISSIONS
    - View Channels
- TEXT PERMISSIONS
    - Send Messages
- VOICE PERMISSIONS
    - なし

生成されたリンクを用いて、用意した discord サーバーに bot を導入します。

## rye のインストール
公式サイト: https://rye.astral.sh/ を参考に導入してください。

## プログラムを実行して動作確認
下のコマンドを順番に実行した後、コマンドを打ち動作していることを確認してください。
```
rye sync
rye run test
```
正常に response があれば準備完了です。

# 開発の仕方
リポジトリのディレクトリ構成は以下のようになっています。
```
.
├── README.md
├── pyproject.toml
├── requirements-dev.lock
├── requirements.lock
└── src
    └── ctfbot
        ├── bot
        │   ├── __init__.py
        │   ├── cogs
        │   │   ├── basic_commands.py
        │   │   ├── manage_cogs.py
        │   │   └── slash_commands.py
        │   └── cogs_loader.py
        └── main.py
```
機能追加は基本的に `./src/ctfbot/bot/cogs` 以下のみをいじることで可能です。

新しい cogs を作る場合は、`./src/ctfbot/bot/cogs_loader.py` 内に cogs を登録する必要があります。

## 実装した機能のテスト
- `source .venv/bin/activate` で python の仮想環境に入ることを忘れないでください。
- `rye run test` で、プログラムを動かしている間は機能のテストができます。

## PR の来た機能のテスト
`{num}` を PR 番号で、`{test}` を好きな文字列で置き換えてください。
```
git fetch origin refs/pull/{num}/head:{test}
git checkout {test}
rye run test
```

## 変更をリポジトリに反映させる
main ブランチは PR 経由の merge でしか変更することができません。
main ブランチに変更を加えたいときは、ブランチを作って PR を送りましょう。

また、PR を merge するには1人以上の review を受けることが必須になっています。
PR を作成したときは誰かしらを reviewer に指定すると良いでしょう。
