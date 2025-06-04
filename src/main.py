import asyncio

from bot import create_bot, run_bot


async def main() -> None:
    bot = create_bot()
    await run_bot(bot)


if __name__ == "__main__":
    asyncio.run(main())
