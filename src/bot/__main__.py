from bot.app import create_bot, run_bot


def main() -> None:
    bot = create_bot()
    run_bot(bot)


if __name__ == "__main__":
    main()
