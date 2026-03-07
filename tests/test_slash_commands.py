import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from discord import app_commands
from discord.ext import commands

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.cogs.help_command import HelpCommand  # noqa: E402
from bot.cogs.perms_debug import PermissionsDebug  # noqa: E402
from bot.cogs.times_channels import TimesChannels  # noqa: E402


class _FakeTextChannel:
    def __init__(
        self,
        *,
        view_channel: bool,
        send_messages: bool,
        send_messages_in_threads: bool,
        read_message_history: bool,
        add_reactions: bool,
        pin_messages: bool,
        manage_channels: bool,
    ) -> None:
        self.mention = "#ctf-test"
        self._perms = type(
            "ChannelPerms",
            (),
            {
                "view_channel": view_channel,
                "send_messages": send_messages,
                "send_messages_in_threads": send_messages_in_threads,
                "read_message_history": read_message_history,
                "add_reactions": add_reactions,
                "pin_messages": pin_messages,
                "manage_channels": manage_channels,
            },
        )()

    def permissions_for(self, _member: object) -> object:
        return self._perms


class _FakeTimesCategory:
    def __init__(
        self,
        *,
        name: str = "times",
        existing_names: list[str] | None = None,
        can_manage_channels: bool = True,
    ) -> None:
        self.name = name
        self._can_manage_channels = can_manage_channels
        self.created_names: list[str] = []
        self.channels = [
            SimpleNamespace(name=channel_name, mention=f"#{channel_name}")
            for channel_name in (existing_names or [])
        ]

    def permissions_for(self, _member: object) -> object:
        return SimpleNamespace(manage_channels=self._can_manage_channels)

    async def create_text_channel(self, name: str, *, reason: str) -> object:
        _ = reason
        channel = SimpleNamespace(name=name, mention=f"#{name}")
        self.channels.append(channel)
        self.created_names.append(name)
        return channel


class _FakeGuild:
    def __init__(self, categories: list[object]) -> None:
        self.id = 123
        self.categories = categories


class _FakeAppCommandTree:
    def __init__(
        self,
        *,
        global_commands: list[app_commands.Command | app_commands.Group] | None = None,
        guild_commands: list[app_commands.Command | app_commands.Group] | None = None,
    ) -> None:
        self._global_commands = global_commands or []
        self._guild_commands = guild_commands or []

    def get_commands(
        self,
        *,
        guild: object | None = None,
        type: object | None = None,
    ) -> list[app_commands.Command | app_commands.Group]:
        _ = type
        if guild is None:
            return list(self._global_commands)
        return list(self._guild_commands)


class _FakeBot:
    def __init__(self, *, tree: _FakeAppCommandTree | None = None) -> None:
        self.user = type("BotUser", (), {"id": 999})()
        self.tree = tree or _FakeAppCommandTree()


def _build_echo_command() -> app_commands.Command:
    @app_commands.command(name="echo", description="メッセージを送信します。")
    async def echo(interaction: object, message: str) -> None:
        _ = interaction, message

    return echo


def _build_ctf_role_group() -> app_commands.Group:
    class _CTFRoleGroup(
        app_commands.Group,
        name="ctfteam",
        description="CTF参加ロール募集を管理します。",
    ):
        @app_commands.command(
            name="open",
            description="CTF募集メッセージを作成します。",
        )
        async def open(self, interaction: object) -> None:
            _ = interaction

    return _CTFRoleGroup()


class HelpCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_help_lists_global_and_guild_slash_commands(self) -> None:
        tree = _FakeAppCommandTree(
            global_commands=[_build_echo_command()],
            guild_commands=[_build_ctf_role_group()],
        )
        bot = cast(commands.Bot, _FakeBot(tree=tree))
        cog = HelpCommand(bot)
        interaction: Any = SimpleNamespace(guild=SimpleNamespace(id=123))

        with patch(
            "bot.cogs.help_command.send_interaction_message",
            new=AsyncMock(),
        ) as send_mock:
            await HelpCommand.help.callback(cog, interaction)

        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("利用可能なスラッシュコマンド", sent_content)
        self.assertIn("/echo", sent_content)
        self.assertIn("/ctfteam open", sent_content)
        self.assertTrue(await_args.kwargs["ephemeral"])

    async def test_help_shows_empty_message_when_no_slash_commands(self) -> None:
        tree = _FakeAppCommandTree(global_commands=[], guild_commands=[])
        bot = cast(commands.Bot, _FakeBot(tree=tree))
        cog = HelpCommand(bot)
        interaction: Any = SimpleNamespace(guild=None)

        with patch(
            "bot.cogs.help_command.send_interaction_message",
            new=AsyncMock(),
        ) as send_mock:
            await HelpCommand.help.callback(cog, interaction)

        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("利用可能なスラッシュコマンドはありません。", sent_content)


class PermissionsDebugTests(unittest.IsolatedAsyncioTestCase):
    async def test_perms_shows_guild_and_channel_permissions(self) -> None:
        bot = cast(commands.Bot, _FakeBot())
        cog = PermissionsDebug(bot)

        interaction: Any = SimpleNamespace(
            guild=object(),
            channel=_FakeTextChannel(
                view_channel=True,
                send_messages=True,
                send_messages_in_threads=True,
                read_message_history=True,
                add_reactions=True,
                pin_messages=True,
                manage_channels=True,
            ),
        )

        member: Any = SimpleNamespace(
            mention="<@999>",
            guild_permissions=SimpleNamespace(
                manage_roles=True,
            ),
            top_role=SimpleNamespace(name="bot", position=8),
        )

        with (
            patch("bot.cogs.perms_debug.discord.TextChannel", _FakeTextChannel),
            patch.object(cog, "_fetch_member", new=AsyncMock(return_value=member)),
            patch(
                "bot.cogs.perms_debug.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await PermissionsDebug.perms.callback(cog, interaction, None)

        self.assertTrue(send_mock.await_count == 1)
        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("Guild Permissions", sent_content)
        self.assertIn("Channel Permissions", sent_content)
        self.assertIn("Manage Roles", sent_content)
        self.assertIn("Add Reactions", sent_content)
        self.assertIn("Pin Messages", sent_content)
        self.assertIn("Send Messages in Threads", sent_content)
        self.assertNotIn("/ctfteam open", sent_content)

    async def test_perms_shows_disabled_permissions(self) -> None:
        bot = cast(commands.Bot, _FakeBot())
        cog = PermissionsDebug(bot)

        interaction: Any = SimpleNamespace(
            guild=object(),
            channel=_FakeTextChannel(
                view_channel=True,
                send_messages=True,
                send_messages_in_threads=False,
                read_message_history=False,
                add_reactions=False,
                pin_messages=False,
                manage_channels=False,
            ),
        )

        member: Any = SimpleNamespace(
            mention="<@999>",
            guild_permissions=SimpleNamespace(
                manage_roles=True,
            ),
            top_role=SimpleNamespace(name="bot", position=8),
        )

        with (
            patch("bot.cogs.perms_debug.discord.TextChannel", _FakeTextChannel),
            patch.object(cog, "_fetch_member", new=AsyncMock(return_value=member)),
            patch(
                "bot.cogs.perms_debug.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await PermissionsDebug.perms.callback(cog, interaction, None)

        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("❌ Manage Channels", sent_content)
        self.assertIn("❌ Add Reactions", sent_content)
        self.assertIn("❌ Pin Messages", sent_content)
        self.assertIn("❌ Send Messages in Threads", sent_content)
        self.assertIn("Manage Channels", sent_content)
        self.assertIn("Add Reactions", sent_content)
        self.assertNotIn("/ctfteam open", sent_content)


class TimesChannelsTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_times_rejects_when_times_category_missing(self) -> None:
        bot = cast(commands.Bot, _FakeBot())
        cog = TimesChannels(bot)
        interaction: Any = SimpleNamespace(
            guild=_FakeGuild(categories=[]),
            user=SimpleNamespace(id=42),
        )

        with patch(
            "bot.cogs.times_channels.send_interaction_message",
            new=AsyncMock(),
        ) as send_mock:
            await TimesChannels.create_times.callback(cog, interaction, "web")

        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("`times` カテゴリが見つかりません", sent_content)

    async def test_create_times_creates_only_missing_channels(self) -> None:
        bot = cast(commands.Bot, _FakeBot())
        cog = TimesChannels(bot)
        times_category = _FakeTimesCategory(existing_names=["web"])
        interaction: Any = SimpleNamespace(
            guild=_FakeGuild(categories=[times_category]),
            user=SimpleNamespace(id=42),
        )
        bot_member = SimpleNamespace()

        with (
            patch.object(cog, "_fetch_member", new=AsyncMock(return_value=bot_member)),
            patch(
                "bot.cogs.times_channels.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await TimesChannels.create_times.callback(cog, interaction, "web,pwn,rev")

        self.assertEqual(times_category.created_names, ["pwn", "rev"])
        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("#pwn", sent_content)
        self.assertIn("#rev", sent_content)
        self.assertIn("既存のためスキップ", sent_content)
        self.assertIn("`web`", sent_content)

    async def test_create_times_normalizes_and_deduplicates_names(self) -> None:
        bot = cast(commands.Bot, _FakeBot())
        cog = TimesChannels(bot)
        times_category = _FakeTimesCategory(existing_names=[])
        interaction: Any = SimpleNamespace(
            guild=_FakeGuild(categories=[times_category]),
            user=SimpleNamespace(id=42),
        )
        bot_member = SimpleNamespace()

        with (
            patch.object(cog, "_fetch_member", new=AsyncMock(return_value=bot_member)),
            patch(
                "bot.cogs.times_channels.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await TimesChannels.create_times.callback(
                cog, interaction, " Web, web, !!!, rev team"
            )

        self.assertEqual(times_category.created_names, ["web", "rev-team"])
        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("無効な入力", sent_content)
        self.assertIn("`!!!`", sent_content)

    async def test_create_times_requires_bot_manage_channels_permission(self) -> None:
        bot = cast(commands.Bot, _FakeBot())
        cog = TimesChannels(bot)
        times_category = _FakeTimesCategory(
            existing_names=[],
            can_manage_channels=False,
        )
        interaction: Any = SimpleNamespace(
            guild=_FakeGuild(categories=[times_category]),
            user=SimpleNamespace(id=42),
        )
        bot_member = SimpleNamespace()

        with (
            patch.object(cog, "_fetch_member", new=AsyncMock(return_value=bot_member)),
            patch(
                "bot.cogs.times_channels.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await TimesChannels.create_times.callback(cog, interaction, "web")

        self.assertEqual(times_category.created_names, [])
        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("Manage Channels", sent_content)


if __name__ == "__main__":
    unittest.main()
