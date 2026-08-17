import sys
from pathlib import Path


def ensure_project_venv() -> None:
    expected = Path(__file__).resolve().parents[2] / ".venv"
    if Path(sys.prefix).resolve() != expected:
        sys.exit(
            f"プロジェクトの venv ({expected}) 以外の Python で起動されました。"
            " `uv run --locked --env-file .env -m ctfbot` で起動してください。"
        )


def main() -> None:
    ensure_project_venv()
    # 依存の import 失敗より先に venv の判定結果を出すため、ここで import する
    from ctfbot.app import create_bot, run_bot

    bot = create_bot()
    run_bot(bot)


if __name__ == "__main__":
    main()
