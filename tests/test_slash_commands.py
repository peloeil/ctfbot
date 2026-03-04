import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from discord.ext import commands

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.cogs.slash_commands import SlashCommands  # noqa: E402


class _FakeTextChannel:
    def __init__(
        self,
        *,
        view_channel: bool,
        send_messages: bool,
        add_reactions: bool,
        manage_messages: bool,
    ) -> None:
        self.mention = "#ctf-test"
        self._perms = type(
            "ChannelPerms",
            (),
            {
                "view_channel": view_channel,
                "send_messages": send_messages,
                "add_reactions": add_reactions,
                "manage_messages": manage_messages,
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


class _FakeBot:
    def __init__(self) -> None:
        self.user = type("BotUser", (), {"id": 999})()


class SlashCommandsTests(unittest.IsolatedAsyncioTestCase):
    async def test_perms_shows_guild_and_channel_permissions(self) -> None:
        bot = cast(commands.Bot, _FakeBot())
        cog = SlashCommands(bot)

        interaction: Any = SimpleNamespace(
            guild=object(),
            channel=_FakeTextChannel(
                view_channel=True,
                send_messages=True,
                add_reactions=True,
                manage_messages=True,
            ),
        )

        member: Any = SimpleNamespace(
            mention="<@999>",
            guild_permissions=SimpleNamespace(
                manage_roles=True,
                manage_channels=True,
                manage_messages=True,
            ),
            top_role=SimpleNamespace(name="bot", position=8),
        )

        with (
            patch("bot.cogs.slash_commands.discord.TextChannel", _FakeTextChannel),
            patch.object(cog, "_fetch_member", new=AsyncMock(return_value=member)),
            patch(
                "bot.cogs.slash_commands.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await SlashCommands.perms.callback(cog, interaction, None)

        self.assertTrue(send_mock.await_count == 1)
        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("Guild Permissions", sent_content)
        self.assertIn("Channel Permissions", sent_content)
        self.assertIn("Manage Roles", sent_content)
        self.assertIn("Add Reactions", sent_content)
        self.assertNotIn("/ctf-role create", sent_content)

    async def test_perms_shows_disabled_permissions(self) -> None:
        bot = cast(commands.Bot, _FakeBot())
        cog = SlashCommands(bot)

        interaction: Any = SimpleNamespace(
            guild=object(),
            channel=_FakeTextChannel(
                view_channel=True,
                send_messages=True,
                add_reactions=False,
                manage_messages=False,
            ),
        )

        member: Any = SimpleNamespace(
            mention="<@999>",
            guild_permissions=SimpleNamespace(
                manage_roles=True,
                manage_channels=False,
                manage_messages=True,
            ),
            top_role=SimpleNamespace(name="bot", position=8),
        )

        with (
            patch("bot.cogs.slash_commands.discord.TextChannel", _FakeTextChannel),
            patch.object(cog, "_fetch_member", new=AsyncMock(return_value=member)),
            patch(
                "bot.cogs.slash_commands.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await SlashCommands.perms.callback(cog, interaction, None)

        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("❌ Manage Channels", sent_content)
        self.assertIn("❌ Add Reactions", sent_content)
        self.assertIn("Manage Channels", sent_content)
        self.assertIn("Add Reactions", sent_content)
        self.assertNotIn("/ctf-role create", sent_content)

    async def test_create_times_rejects_when_times_category_missing(self) -> None:
        bot = cast(commands.Bot, _FakeBot())
        cog = SlashCommands(bot)
        interaction: Any = SimpleNamespace(
            guild=_FakeGuild(categories=[]),
            user=SimpleNamespace(id=42),
        )

        with patch(
            "bot.cogs.slash_commands.send_interaction_message",
            new=AsyncMock(),
        ) as send_mock:
            await SlashCommands.create_times.callback(cog, interaction, "web")

        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("`times` カテゴリが見つかりません", sent_content)

    async def test_create_times_creates_only_missing_channels(self) -> None:
        bot = cast(commands.Bot, _FakeBot())
        cog = SlashCommands(bot)
        times_category = _FakeTimesCategory(existing_names=["web"])
        interaction: Any = SimpleNamespace(
            guild=_FakeGuild(categories=[times_category]),
            user=SimpleNamespace(id=42),
        )
        bot_member = SimpleNamespace()

        with (
            patch.object(cog, "_fetch_member", new=AsyncMock(return_value=bot_member)),
            patch(
                "bot.cogs.slash_commands.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await SlashCommands.create_times.callback(cog, interaction, "web,pwn,rev")

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
        cog = SlashCommands(bot)
        times_category = _FakeTimesCategory(existing_names=[])
        interaction: Any = SimpleNamespace(
            guild=_FakeGuild(categories=[times_category]),
            user=SimpleNamespace(id=42),
        )
        bot_member = SimpleNamespace()

        with (
            patch.object(cog, "_fetch_member", new=AsyncMock(return_value=bot_member)),
            patch(
                "bot.cogs.slash_commands.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await SlashCommands.create_times.callback(
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
        cog = SlashCommands(bot)
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
                "bot.cogs.slash_commands.send_interaction_message",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await SlashCommands.create_times.callback(cog, interaction, "web")

        self.assertEqual(times_category.created_names, [])
        await_args = send_mock.await_args
        assert await_args is not None
        sent_content = await_args.args[1]
        self.assertIn("Manage Channels", sent_content)


if __name__ == "__main__":
    unittest.main()
