import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from discord.ext import commands

from ctfbot.app import CTFBot, create_bot
from ctfbot.cogs_loader import DEFAULT_EXTENSIONS
from ctfbot.runtime import BotRuntime


def settings(tts_enabled: bool = False) -> Any:
    return SimpleNamespace(
        guild_id=999,
        database_path=":memory:",
        log_level="INFO",
        tts_enabled=tts_enabled,
    )


async def loaded_extensions(bot: CTFBot) -> tuple[str, ...]:
    tree = mock.Mock()
    tree.sync = mock.AsyncMock(return_value=[])
    with (
        mock.patch("ctfbot.app.load_cogs", new_callable=mock.AsyncMock) as load_cogs,
        mock.patch.object(CTFBot, "tree", new_callable=mock.PropertyMock) as tree_prop,
    ):
        tree_prop.return_value = tree
        await bot.setup_hook()
    assert load_cogs.await_args is not None
    return load_cogs.await_args.args[1]


class AppTest(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def runtime() -> BotRuntime:
        return BotRuntime(settings=settings(), db=mock.Mock())

    async def test_mention_chat_keeps_message_content_intent_off(self) -> None:
        bot = CTFBot(self.runtime())
        self.assertFalse(bot.intents.message_content)

    async def test_unknown_mention_command_is_ignored(self) -> None:
        bot = CTFBot(self.runtime())
        with mock.patch.object(
            commands.Bot, "on_command_error", new_callable=mock.AsyncMock
        ) as parent:
            await bot.on_command_error(mock.Mock(), commands.CommandNotFound("unknown"))
        parent.assert_not_awaited()

    async def test_other_command_errors_are_delegated_to_discord_py(self) -> None:
        bot = CTFBot(self.runtime())
        with mock.patch.object(
            commands.Bot, "on_command_error", new_callable=mock.AsyncMock
        ) as parent:
            await bot.on_command_error(mock.Mock(), commands.CommandError("failed"))
        parent.assert_awaited_once()

    async def test_setup_hook_syncs_commands_to_the_configured_guild_only(
        self,
    ) -> None:
        bot = CTFBot(self.runtime())
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

    async def test_command_completion_log_shows_names_with_ids(self) -> None:
        bot = CTFBot(self.runtime())
        command = cast(Any, SimpleNamespace(qualified_name="ctf list"))
        user = SimpleNamespace(name="alice", id=1)
        cases = {
            "named channel": (SimpleNamespace(name="general"), "#general(2)"),
            "channel without name": (SimpleNamespace(), "unknown(2)"),
            "missing channel": (None, "unknown(2)"),
        }
        for label, (channel, expected) in cases.items():
            with self.subTest(label):
                interaction = cast(
                    Any, SimpleNamespace(user=user, channel=channel, channel_id=2)
                )
                with self.assertLogs("ctfbot", level="INFO") as logs:
                    await bot.on_app_command_completion(interaction, command)
                self.assertEqual(
                    logs.records[0].getMessage(),
                    "Application command completed: command=/ctf list "
                    f"user=alice(1) channel={expected}",
                )

    async def test_create_bot_loads_private_extensions_after_defaults(self) -> None:
        with mock.patch("ctfbot.app.Database", return_value=mock.Mock()):
            bot = create_bot(settings(), extra_extensions=("private_bot.feature",))

        self.assertEqual(
            await loaded_extensions(bot),
            (*DEFAULT_EXTENSIONS, "private_bot.feature"),
        )

    def test_create_bot_message_content_intent(self) -> None:
        cases = (
            (False, False, False),
            (False, True, True),
            (True, False, True),
            (True, True, True),
        )
        for tts_enabled, message_content, expected in cases:
            with self.subTest(tts_enabled=tts_enabled, message_content=message_content):
                with mock.patch("ctfbot.app.Database", return_value=mock.Mock()):
                    bot = create_bot(
                        settings(tts_enabled),
                        message_content=message_content,
                    )
                self.assertEqual(bot.intents.message_content, expected)
