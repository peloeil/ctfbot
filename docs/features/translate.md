# 翻訳

`/translate` とメッセージの右クリック「メッセージを翻訳」で、テキストを日本語または英語に翻訳する。結果は実行者だけに ephemeral で返す。`TRANSLATE_API_URL` が未設定なら機能全体が無効で、cog を追加せず、コマンドも `/help` に出ない。

実装: [translate.py](../../src/ctfbot/features/translate.py)、コンテナの起動・停止は TTS と共通の [podman.py](../../src/ctfbot/podman.py)。検証: [test_translate.py](../../tests/test_translate.py)。

## モデルと実行環境

PLaMo 3 Translate 0.8B の公式 GGUF（Q4_K_M）を llama.cpp のサーバーで動かす。デスクトップと同居するため、常駐はせず bot が podman コンテナを必要なときだけ起動し、最後の利用から 5 分で停止する。実測では 0.8B Q4_K_M が生成 88 tok/s、短文の翻訳が 0.4–0.5 秒、コンテナのメモリ使用量が約 0.4GB だった（Ryzen 9 7900X、12 スレッド）。コンテナには `--memory=2g` を設定し、モデルが想定外にメモリを食ってもデスクトップを巻き込まないようにする。

モデルのライセンスは [PLaMo Community License](https://plamo.preferredai.jp/info/plamo-community-license-ja)。個人利用・非商用利用は無償で、法人の商用利用は売上に応じた登録または契約が必要になる。

### コンテナの準備

モデルを取得する。

```bash
mkdir -p ~/.local/share/plamo-3-translate
curl -L -o ~/.local/share/plamo-3-translate/plamo-3-translate-0.8b-Q4_K_M.gguf \
  https://huggingface.co/pfnet/plamo-3-translate-0.8b-GGUF/resolve/main/plamo-3-translate-0.8b-Q4_K_M.gguf
```

コンテナを作成する。bot はこのコンテナを `podman start` / `podman stop` するだけで、作成・削除はしない。

```bash
podman create --name plamo-translate --memory=2g \
  -p 127.0.0.1:8080:8080 \
  -v "$HOME/.local/share/plamo-3-translate:/models:ro" \
  ghcr.io/ggml-org/llama.cpp:server \
  --model /models/plamo-3-translate-0.8b-Q4_K_M.gguf \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 4096 --threads 12 --parallel 1 --no-webui
```

`--threads` は物理コア数に合わせる。24 スレッドにすると 8B では生成が遅くなったため、7900X では 12 にしている。`--parallel 1` は同時リクエストをサーバー側で直列化する。bot 側も同時 2 件までに制限する。

`.env` の `TRANSLATE_API_URL` に `http://127.0.0.1:8080` を設定する。URL はベース URL で、bot は `/health` と `/v1/completions` を呼ぶ。コンテナ名は `TRANSLATE_CONTAINER`、リクエストの `model` は `TRANSLATE_MODEL` で変更できる。

## 翻訳の挙動

- 仮名（ひらがな・カタカナ）を含む文は英語へ、含まない文は日本語へ翻訳する。中国語など漢字だけの文は日本語向けに倒す。
- `/translate` の `target` で `日本語` / `English` を明示できる。省略時は自動。仮名を含む文を `日本語` 指定で翻訳する場合は、英語交じりの文とみなし、原文の言語をモデルに判定させる（日本語→日本語の指定にしない）。
- 入力の上限は翻訳先で変える。日本語へは `TRANSLATE_MAX_CHARS`（既定 2000、上限 2000）文字まで、英語へは 600 文字（`TRANSLATE_MAX_CHARS` が小さければそちら）まで。英訳は日本語の 2〜3 倍の文字数になり、600 文字を超えると結果が 1900 文字に収まらず後半が切れるためだ。日本語訳は原文より短くなるので 2000 文字でも収まる。空白だけの入力は案内する。長い日本語の英訳が必要になったら、出力を複数メッセージに分ける方式を検討する（`--ctx-size` の拡張と、長文での 0.8B の品質確認が前提）。
- PFML3 の制御トークン（`<|plamo:`）を含む入力は、プロンプトへの注入を避けるため断る。
- 結果が 1900 文字を超えたら末尾を省略する。メンションと返信先への通知は抑止する。
- 翻訳に失敗した場合は「翻訳結果を取得できませんでした。」を返し、再試行しない。
- 同時実行は bot 全体で 2 件まで。超えた場合は混雑として断る。

翻訳対象の本文はローカルの llama.cpp にだけ送り、DB に保存しない。ログには本文を出さず、文字数だけを残す。

## 起動と停止

- 最初の翻訳要求でコンテナを起動し、`/health` が通るまで待つ。実測（7900X、0.8B Q4_K_M）では `podman start` 0.17 秒、モデル読み込みを含む `/health` 応答まで 1.4 秒、短文の翻訳 0.13 秒で、停止中からの最初の翻訳は約 1.7 秒、起動済みなら約 0.12 秒だった。`podman stop` は 0.3 秒。
- 最後の利用から 5 分経つと `podman stop` する。処理中は停止しない。
- bot の停止時（cog unload）にもコンテナを止める。
- bot 再起動時、前回のプロセスが残したコンテナは 5 分後に停止する。
- `podman start` / `stop` の失敗、ヘルスチェックのタイムアウトは翻訳失敗として扱う。コンテナが外部で停止された場合、次の要求で起動し直す。

## 運用

コマンドは guild 限定で、応答はすべて ephemeral。メッセージの右クリックから使う場合も、本文のあるメッセージだけを対象にする。添付・埋め込み・スタンプは翻訳しない。

0.8B は速度とメモリを優先した選択で、品質は 2B・8B より低い。品質を上げる場合は、コンテナの `--model` を差し替える。8B Q4_K_M は短文で 4–5 秒、ネイティブ実行時の RSS 約 9GB だった。
