import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from discord.ext import commands

from ctfbot.app import CTFBot, create_bot
from ctfbot.cogs_loader import DEFAULT_EXTENSIONS
from ctfbot.runtime import BotRuntime


class AppTest(unittest.IsolatedAsyncioTestCase):
    async def test_mention_chat_keeps_message_content_intent_off(self) -> None:
        runtime = BotRuntime(
            settings=cast(Any, SimpleNamespace(guild_id=999, tts_enabled=False)),
            db=mock.Mock(),
        )
        bot = CTFBot(runtime)
        self.assertFalse(bot.intents.message_content)

    async def test_unknown_mention_command_is_ignored(self) -> None:
        runtime = BotRuntime(
            settings=cast(Any, SimpleNamespace(guild_id=999, tts_enabled=False)),
            db=mock.Mock(),
        )
        bot = CTFBot(runtime)
        with mock.patch.object(
            commands.Bot, "on_command_error", new_callable=mock.AsyncMock
        ) as parent:
            await bot.on_command_error(mock.Mock(), commands.CommandNotFound("unknown"))
            parent.assert_not_awaited()
            await bot.on_command_error(mock.Mock(), commands.CommandError("failed"))
            parent.assert_awaited_once()

    async def test_setup_hook_syncs_commands_to_the_configured_guild_only(
        self,
    ) -> None:
        runtime = BotRuntime(
            settings=cast(Any, SimpleNamespace(guild_id=999, tts_enabled=False)),
            db=mock.Mock(),
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
                tts_enabled=False,
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

    def test_create_bot_enables_message_content_only_with_tts(self) -> None:
        for tts_enabled in (False, True):
            with self.subTest(tts_enabled=tts_enabled):
                settings = cast(
                    Any,
                    SimpleNamespace(
                        database_path=":memory:",
                        log_level="INFO",
                        tts_enabled=tts_enabled,
                    ),
                )
                with mock.patch("ctfbot.app.Database", return_value=mock.Mock()):
                    bot = create_bot(settings)
                self.assertEqual(bot.intents.message_content, tts_enabled)
