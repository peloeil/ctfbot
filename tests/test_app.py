import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from ctfbot.app import CTFBot, create_bot
from ctfbot.cogs_loader import DEFAULT_EXTENSIONS
from ctfbot.runtime import BotRuntime


class AppTest(unittest.IsolatedAsyncioTestCase):
    async def test_setup_hook_syncs_commands_to_the_configured_guild_only(
        self,
    ) -> None:
        runtime = BotRuntime(
            settings=cast(Any, SimpleNamespace(guild_id=999)), db=mock.Mock()
        )
        bot = CTFBot(runtime)
        tree = mock.Mock()
        tree.sync = mock.AsyncMock(return_value=[])

        with (
            mock.patch(
                "ctfbot.app.load_cogs", new_callable=mock.AsyncMock
            ) as load_cogs,
            mock.patch.object(
                CTFBot, "tree", new_callable=mock.PropertyMock
            ) as tree_prop,
        ):
            tree_prop.return_value = tree
            await bot.setup_hook()

        load_cogs.assert_awaited_once_with(bot, DEFAULT_EXTENSIONS)
        tree.copy_global_to.assert_called_once()
        guild = tree.copy_global_to.call_args.kwargs["guild"]
        self.assertEqual(guild.id, 999)
        self.assertEqual(tree.sync.await_args_list, [mock.call(guild=guild)])
        tree.clear_commands.assert_not_called()

    def test_create_bot_accepts_private_extensions_and_message_content(self) -> None:
        settings = cast(
            Any,
            SimpleNamespace(
                database_path=":memory:",
                log_level="INFO",
            ),
        )

        with mock.patch("ctfbot.app.Database", return_value=mock.Mock()):
            bot = create_bot(
                settings,
                extra_extensions=("private_bot.feature",),
                message_content=True,
            )

        self.assertEqual(
            bot._extension_names,
            (*DEFAULT_EXTENSIONS, "private_bot.feature"),
        )
        self.assertTrue(bot.intents.message_content)
