from bot.app import create_bot, run_bot


def main() -> None:
    instance = create_bot()
    run_bot(instance)


if __name__ == "__main__":
    main()
