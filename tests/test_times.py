import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import discord

from ctfbot.features.times import TimesChannels
from ctfbot.runtime import BotRuntime

BOT_CHANNEL_ID = 900


class TimesChannelsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.audit_channel = mock.Mock(spec=discord.TextChannel)
        self.audit_channel.send = mock.AsyncMock()
        self.bot = mock.Mock()
        self.bot.get_channel.side_effect = lambda channel_id: (
            self.audit_channel if channel_id == BOT_CHANNEL_ID else None
        )
        self.bot.runtime = BotRuntime(
            settings=cast(
                Any,
                SimpleNamespace(times_category_id=55, bot_channel_id=BOT_CHANNEL_ID),
            ),
            db=mock.Mock(),
        )
        self.cog = TimesChannels(self.bot)

    def make_interaction(self, guild: discord.Guild) -> tuple[Any, Any]:
        response = mock.Mock()
        response.is_done.return_value = False
        response.send_message = mock.AsyncMock()
        interaction = SimpleNamespace(
            guild=guild,
            response=response,
            user=SimpleNamespace(id=7, name="alice"),
            channel=SimpleNamespace(name="general"),
            channel_id=2,
        )
        return interaction, response.send_message

    def make_guild(
        self, category: discord.CategoryChannel
    ) -> tuple[mock.Mock, mock.AsyncMock]:
        guild = mock.Mock(spec=discord.Guild)
        guild.get_channel.return_value = category
        guild.create_text_channel = mock.AsyncMock(
            side_effect=lambda name, category: SimpleNamespace(
                name=name, mention="<#101>"
            )
        )
        return guild, guild.create_text_channel

    @staticmethod
    def make_category(*text_channels: object) -> mock.Mock:
        category = mock.Mock(spec=discord.CategoryChannel)
        category.text_channels = list(text_channels)
        return category

    async def create(self, interaction: Any, name: str) -> None:
        callback = cast(Any, self.cog.create_times.callback)
        await callback(self.cog, interaction, name)

    async def test_create_times_normalizes_name_and_creates_channel(self) -> None:
        category = self.make_category(SimpleNamespace(name="existing"))
        guild, create_text_channel = self.make_guild(category)
        interaction, send_message = self.make_interaction(guild)

        await self.create(interaction, "Alpha Team")

        create_text_channel.assert_awaited_once_with(
            name="alpha-team", category=category
        )
        self.assertEqual(send_message.await_args.args[0], "✅ <#101> を作成しました。")

    async def test_create_times_notifies_audit_channel(self) -> None:
        guild, _ = self.make_guild(self.make_category())
        interaction, _ = self.make_interaction(guild)

        await self.create(interaction, "alpha")

        content = self.audit_channel.send.await_args.args[0]
        self.assertIn("<@7>", content)
        self.assertIn("`/times create`", content)
        self.assertIn("- 作成: <#101>", content)

    async def test_create_times_skips_existing_channel_without_audit(self) -> None:
        category = self.make_category(SimpleNamespace(name="existing", mention="<#77>"))
        guild, create_text_channel = self.make_guild(category)
        interaction, send_message = self.make_interaction(guild)

        await self.create(interaction, "Existing")

        create_text_channel.assert_not_awaited()
        self.assertEqual(send_message.await_args.args[0], "⏭️ <#77> は既に存在します。")
        self.audit_channel.send.assert_not_awaited()

    async def test_create_times_rejects_name_that_normalizes_to_empty(self) -> None:
        guild, create_text_channel = self.make_guild(self.make_category())
        interaction, send_message = self.make_interaction(guild)

        await self.create(interaction, "、、、")

        create_text_channel.assert_not_awaited()
        self.assertEqual(
            send_message.await_args.args[0], "作成するチャンネル名を入力してください。"
        )
        self.audit_channel.send.assert_not_awaited()

    async def test_create_times_reports_when_feature_is_not_configured(self) -> None:
        self.cog.settings = cast(Any, SimpleNamespace(times_category_id=None))
        guild = mock.Mock(spec=discord.Guild)
        interaction, send_message = self.make_interaction(guild)

        await self.create(interaction, "example")

        guild.get_channel.assert_not_called()
        self.assertEqual(
            send_message.await_args.args[0], "times 機能が設定されていません。"
        )

    async def test_create_times_reports_when_category_cannot_be_resolved(self) -> None:
        guild = mock.Mock(spec=discord.Guild)
        guild.get_channel.return_value = mock.Mock(spec=discord.TextChannel)
        interaction, send_message = self.make_interaction(guild)

        await self.create(interaction, "example")

        guild.get_channel.assert_called_once_with(55)
        self.assertEqual(
            send_message.await_args.args[0], "times カテゴリが見つかりません。"
        )
