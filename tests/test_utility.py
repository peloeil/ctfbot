import unittest
from typing import Any, cast
from unittest import mock

import discord
from discord import app_commands

from ctfbot.features.utility import (
    UtilityCommands,
    _format_permissions,
    _guild_permissions_for,
    _permission_pages,
)
from ctfbot.helpers import MAX_MESSAGE_CONTENT_LENGTH


async def _noop(interaction: discord.Interaction) -> None:
    return None


def make_command(name: str, description: str) -> app_commands.Command:
    return app_commands.Command(name=name, description=description, callback=_noop)


class UtilityCommandsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot = mock.Mock()
        self.cog = UtilityCommands(self.bot)
        self.interaction = mock.Mock(spec=discord.Interaction)
        self.interaction.guild = mock.Mock(spec=discord.Guild)
        self.interaction.response = mock.Mock()
        self.interaction.response.is_done.return_value = False
        self.interaction.response.send_message = mock.AsyncMock()

    async def invoke_help(self) -> None:
        callback = cast(Any, self.cog.help_command.callback)
        await callback(self.cog, self.interaction)

    async def invoke_roll(self, notation: str) -> None:
        callback = cast(Any, self.cog.roll.callback)
        await callback(self.cog, self.interaction, notation)

    async def invoke_perms(
        self,
        channel: discord.TextChannel | None = None,
        role: discord.Role | None = None,
    ) -> None:
        callback = cast(Any, self.cog.perms_check.callback)
        await callback(self.cog, self.interaction, channel, role)

    @mock.patch("ctfbot.features.utility.random.randint", side_effect=[2, 5, 1])
    async def test_roll_rolls_ndm_and_reports_total(self, randint: mock.Mock) -> None:
        await self.invoke_roll("3d6")

        self.assertEqual(randint.call_args_list, [mock.call(1, 6)] * 3)
        args, kwargs = self.interaction.response.send_message.await_args
        self.assertEqual(args[0], "🎲 3d6: 2, 5, 1\n合計: 8")
        self.assertFalse(kwargs["ephemeral"])

    async def test_roll_rejects_invalid_notation(self) -> None:
        await self.invoke_roll("3x6")

        args, kwargs = self.interaction.response.send_message.await_args
        self.assertEqual(args[0], "NdM 形式で指定してください (例: 3d6)。")
        self.assertTrue(kwargs["ephemeral"])

    async def test_roll_rejects_values_over_100(self) -> None:
        await self.invoke_roll("101d6")

        args, kwargs = self.interaction.response.send_message.await_args
        self.assertEqual(args[0], "ダイスの個数と面数は 1〜100 で指定してください。")
        self.assertTrue(kwargs["ephemeral"])

    async def test_help_lists_guild_commands_sorted(self) -> None:
        group = app_commands.Group(name="alpaca", description="AlpacaHack コマンド")
        group.add_command(make_command("add", "ユーザー登録"))
        self.bot.tree.get_commands.return_value = [
            make_command("perms", "権限表示"),
            group,
        ]

        await self.invoke_help()

        self.bot.tree.get_commands.assert_called_once_with(guild=self.interaction.guild)
        args, kwargs = self.interaction.response.send_message.await_args
        self.assertEqual(args[0], "/alpaca add — ユーザー登録\n/perms — 権限表示")
        self.assertTrue(kwargs["ephemeral"])
        allowed = kwargs["allowed_mentions"]
        self.assertFalse(allowed.everyone)
        self.assertFalse(allowed.users)
        self.assertFalse(allowed.roles)
        self.assertFalse(allowed.replied_user)

    async def test_help_outside_guild_reports_error(self) -> None:
        self.interaction.guild = None

        await self.invoke_help()

        self.bot.tree.get_commands.assert_not_called()
        args, _ = self.interaction.response.send_message.await_args
        self.assertEqual(args[0], "サーバー内で実行してください。")

    async def test_help_send_failure_is_suppressed(self) -> None:
        self.bot.tree.get_commands.return_value = []
        self.interaction.response.send_message.side_effect = discord.HTTPException(
            mock.Mock(status=500, reason="Internal Server Error"), "boom"
        )

        await self.invoke_help()

        self.interaction.response.send_message.assert_awaited_once()

    async def test_perms_defaults_to_bot_and_current_channel(self) -> None:
        member = mock.Mock(spec=discord.Member)
        member.id = 123
        member.mention = "<@123>"
        member.guild_permissions = discord.Permissions(manage_roles=True)
        self.interaction.guild.me = member
        channel = mock.Mock(spec=discord.TextChannel)
        channel.id = 456
        channel.mention = "<#456>"
        channel.permissions_for.return_value = discord.Permissions(view_channel=True)
        self.interaction.channel = channel

        await self.invoke_perms()

        channel.permissions_for.assert_called_once_with(member)
        args, kwargs = self.interaction.response.send_message.await_args
        self.assertIn("対象: <@123> (ID: 123)", args[0])
        self.assertIn("チャンネル: <#456> (ID: 456)", args[0])
        self.assertIn("Guild ✅ manage_roles", args[0])
        self.assertIn("Channel 追加 ✅ view_channel", args[0])
        self.assertIn("Channel 削除 ❌ manage_roles", args[0])
        self.assertTrue(kwargs["ephemeral"])

    async def test_perms_combines_everyone_with_selected_role(self) -> None:
        member = mock.Mock(spec=discord.Member)
        self.interaction.guild.me = member
        everyone = mock.Mock(spec=discord.Role)
        everyone.permissions = discord.Permissions(view_channel=True)
        self.interaction.guild.default_role = everyone
        role = mock.Mock(spec=discord.Role)
        role.id = 789
        role.mention = "<@&789>"
        role.position = 4
        role.permissions = discord.Permissions(manage_roles=True)
        channel = mock.Mock(spec=discord.TextChannel)
        channel.id = 456
        channel.mention = "<#456>"
        channel.permissions_for.return_value = discord.Permissions(
            view_channel=True, send_messages=True
        )

        await self.invoke_perms(channel, role)

        channel.permissions_for.assert_called_once_with(role)
        args, _ = self.interaction.response.send_message.await_args
        self.assertIn("対象: <@&789> (ID: 789)", args[0])
        self.assertIn("ロール順位: 4", args[0])
        self.assertIn("Guild ✅ view_channel、manage_roles", args[0])
        self.assertIn("Channel 追加 ✅ send_messages", args[0])
        self.assertIn("Channel 削除 ❌ manage_roles", args[0])


class PermissionFormattingTest(unittest.TestCase):
    def test_format_permissions_lists_every_permission_once(self) -> None:
        permissions = discord.Permissions(manage_roles=True, send_messages=True)

        enabled, disabled = _format_permissions("Guild", permissions)

        self.assertEqual(enabled, "Guild ✅ send_messages、manage_roles")
        disabled_names = disabled.removeprefix("Guild ❌ ").split("、")
        self.assertIn("administrator", disabled_names)
        self.assertNotIn("send_messages", disabled_names)
        self.assertNotIn("manage_roles", disabled_names)

    def test_guild_permissions_expand_administrator(self) -> None:
        guild = mock.Mock(spec=discord.Guild)
        guild.default_role.permissions = discord.Permissions.none()
        role = mock.Mock(spec=discord.Role)
        role.permissions = discord.Permissions(administrator=True)

        permissions = _guild_permissions_for(guild, role)

        self.assertEqual(permissions.value, discord.Permissions.all().value)

    def test_permission_pages_split_before_message_limit(self) -> None:
        header = ["x" * 300]

        pages = _permission_pages(
            header, discord.Permissions.none(), discord.Permissions.all()
        )

        self.assertEqual(len(pages), 2)
        self.assertTrue(all(len(page) <= MAX_MESSAGE_CONTENT_LENGTH for page in pages))
        self.assertTrue(pages[0].startswith(header[0]))
        self.assertTrue(pages[1].startswith("Channel 追加 ✅"))

    def test_permission_pages_report_no_channel_difference(self) -> None:
        permissions = discord.Permissions(view_channel=True, send_messages=True)

        pages = _permission_pages(["対象"], permissions, permissions)

        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].endswith("Channel 差分なし"))
