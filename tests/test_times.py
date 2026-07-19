import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import discord

from bot.features.times import TimesChannels
from bot.runtime import BotRuntime


class TimesChannelsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot = mock.Mock()
        self.bot.runtime = BotRuntime(
            settings=cast(Any, SimpleNamespace(times_category_id=55)), db=mock.Mock()
        )
        self.cog = TimesChannels(self.bot)

    @staticmethod
    def make_interaction(
        category: discord.CategoryChannel,
    ) -> tuple[mock.AsyncMock, discord.Interaction]:
        guild = mock.Mock(spec=discord.Guild)
        guild.get_channel.return_value = category
        guild.create_text_channel = mock.AsyncMock(
            side_effect=lambda name, category: SimpleNamespace(
                name=name, mention="<#101>"
            )
        )
        interaction = SimpleNamespace(guild=guild)
        return guild.create_text_channel, cast(discord.Interaction, interaction)

    async def test_create_times_normalizes_name_and_logs_audit(self) -> None:
        category = mock.Mock(spec=discord.CategoryChannel)
        category.text_channels = [SimpleNamespace(name="existing")]
        create_text_channel, interaction = self.make_interaction(category)

        with (
            mock.patch(
                "bot.features.times.send_interaction", new_callable=mock.AsyncMock
            ) as send_interaction,
            mock.patch(
                "bot.features.times.log_audit", new_callable=mock.AsyncMock
            ) as log_audit,
        ):
            callback = cast(Any, self.cog.create_times.callback)
            await callback(self.cog, interaction, "Alpha Team")

        create_text_channel.assert_awaited_once_with(
            name="alpha-team", category=category
        )
        send_interaction.assert_awaited_once_with(
            interaction, "✅ #alpha-team を作成しました。"
        )
        log_audit.assert_awaited_once_with(
            self.bot,
            interaction,
            command_name="times create",
            details=["作成: <#101>"],
        )

    async def test_create_times_skips_existing_channel_without_audit(self) -> None:
        category = mock.Mock(spec=discord.CategoryChannel)
        category.text_channels = [SimpleNamespace(name="existing")]
        create_text_channel, interaction = self.make_interaction(category)

        with (
            mock.patch(
                "bot.features.times.send_interaction", new_callable=mock.AsyncMock
            ) as send_interaction,
            mock.patch(
                "bot.features.times.log_audit", new_callable=mock.AsyncMock
            ) as log_audit,
        ):
            callback = cast(Any, self.cog.create_times.callback)
            await callback(self.cog, interaction, "Existing")

        create_text_channel.assert_not_awaited()
        send_interaction.assert_awaited_once_with(
            interaction, "⏭️ #existing は既に存在します。"
        )
        log_audit.assert_not_awaited()

    async def test_create_times_rejects_name_that_normalizes_to_empty(self) -> None:
        category = mock.Mock(spec=discord.CategoryChannel)
        category.text_channels = []
        create_text_channel, interaction = self.make_interaction(category)

        with (
            mock.patch(
                "bot.features.times.send_interaction", new_callable=mock.AsyncMock
            ) as send_interaction,
            mock.patch(
                "bot.features.times.log_audit", new_callable=mock.AsyncMock
            ) as log_audit,
        ):
            callback = cast(Any, self.cog.create_times.callback)
            await callback(self.cog, interaction, "、、、")

        create_text_channel.assert_not_awaited()
        send_interaction.assert_awaited_once_with(
            interaction, "作成するチャンネル名を入力してください。"
        )
        log_audit.assert_not_awaited()

    async def test_create_times_reports_when_feature_is_not_configured(self) -> None:
        self.cog.settings = cast(Any, SimpleNamespace(times_category_id=None))
        guild = mock.Mock(spec=discord.Guild)
        interaction = cast(discord.Interaction, SimpleNamespace(guild=guild))

        with mock.patch(
            "bot.features.times.send_interaction", new_callable=mock.AsyncMock
        ) as send_interaction:
            callback = cast(Any, self.cog.create_times.callback)
            await callback(self.cog, interaction, "example")

        guild.get_channel.assert_not_called()
        send_interaction.assert_awaited_once_with(
            interaction, "times 機能が設定されていません。"
        )

    async def test_create_times_reports_when_category_cannot_be_resolved(self) -> None:
        guild = mock.Mock(spec=discord.Guild)
        guild.get_channel.return_value = mock.Mock(spec=discord.TextChannel)
        interaction = cast(discord.Interaction, SimpleNamespace(guild=guild))

        with mock.patch(
            "bot.features.times.send_interaction", new_callable=mock.AsyncMock
        ) as send_interaction:
            callback = cast(Any, self.cog.create_times.callback)
            await callback(self.cog, interaction, "example")

        guild.get_channel.assert_called_once_with(55)
        send_interaction.assert_awaited_once_with(
            interaction, "times カテゴリが見つかりません。"
        )


if __name__ == "__main__":
    unittest.main()
