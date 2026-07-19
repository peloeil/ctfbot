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


class HelpCommandTest(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
