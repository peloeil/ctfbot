import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, call, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot import cogs_loader  # noqa: E402


class CogsLoaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_cogs_loads_all_extensions(self) -> None:
        bot = AsyncMock()
        extensions = (
            "bot.cogs.manage_cogs",
            "bot.cogs.message_tools",
            "bot.features.ctftime.cog",
        )

        with patch.object(cogs_loader, "DEFAULT_EXTENSIONS", extensions):
            await cogs_loader.load_cogs(bot)

        bot.load_extension.assert_has_awaits([call(name) for name in extensions])
        self.assertEqual(bot.load_extension.await_count, len(extensions))

    async def test_load_cogs_fails_fast_on_extension_error(self) -> None:
        bot = AsyncMock()
        extensions = (
            "bot.cogs.manage_cogs",
            "bot.features.ctftime.cog",
            "bot.features.alpacahack.cog",
        )

        async def load_side_effect(name: str) -> None:
            if name == "bot.features.ctftime.cog":
                raise RuntimeError("boom")

        bot.load_extension.side_effect = load_side_effect

        with (
            patch.object(cogs_loader, "DEFAULT_EXTENSIONS", extensions),
            self.assertRaises(RuntimeError) as raised,
        ):
            await cogs_loader.load_cogs(bot)

        self.assertIn("bot.features.ctftime.cog", str(raised.exception))
        self.assertEqual(bot.load_extension.await_count, 2)


if __name__ == "__main__":
    unittest.main()
