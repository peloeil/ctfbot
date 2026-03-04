import asyncio

from bot.app import create_bot, run_bot


async def main() -> None:
    instance = create_bot()
    await run_bot(instance)


if __name__ == "__main__":
    asyncio.run(main())
