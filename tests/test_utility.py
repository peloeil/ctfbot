import unittest
from typing import Any, cast
from unittest import mock

import discord
from discord import app_commands

from bot.features.utility import UtilityCommands


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

    @mock.patch("bot.features.utility.random.randint", side_effect=[2, 5, 1])
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
