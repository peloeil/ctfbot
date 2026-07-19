import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from bot.app import CTFBot
from bot.runtime import BotRuntime


class AppTest(unittest.IsolatedAsyncioTestCase):
    async def test_setup_hook_syncs_configured_guild_and_clears_global(
        self,
    ) -> None:
        runtime = BotRuntime(
            settings=cast(Any, SimpleNamespace(guild_id=999)), db=mock.Mock()
        )
        bot = CTFBot(runtime)
        tree = mock.Mock()
        tree.sync = mock.AsyncMock(return_value=[])

        with (
            mock.patch("bot.app.load_cogs", new_callable=mock.AsyncMock) as load_cogs,
            mock.patch.object(
                CTFBot, "tree", new_callable=mock.PropertyMock
            ) as tree_prop,
        ):
            tree_prop.return_value = tree
            await bot.setup_hook()

        load_cogs.assert_awaited_once_with(bot)
        tree.copy_global_to.assert_called_once()
        guild = tree.copy_global_to.call_args.kwargs["guild"]
        self.assertEqual(guild.id, 999)
        self.assertEqual(
            tree.sync.await_args_list, [mock.call(guild=guild), mock.call()]
        )
        tree.clear_commands.assert_called_once_with(guild=None)
        self.assertLess(
            tree.method_calls.index(mock.call.copy_global_to(guild=guild)),
            tree.method_calls.index(mock.call.clear_commands(guild=None)),
        )


if __name__ == "__main__":
    unittest.main()
