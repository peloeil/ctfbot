import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import discord

from bot.features.times import TimesChannels


class TimesChannelsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot = mock.Mock()
        self.cog = TimesChannels(self.bot)

    @staticmethod
    def make_interaction(
        category: SimpleNamespace,
    ) -> tuple[mock.AsyncMock, discord.Interaction]:
        channel_ids = iter(range(101, 200))
        guild = SimpleNamespace(
            categories=[category],
            create_text_channel=mock.AsyncMock(
                side_effect=lambda name, category: SimpleNamespace(
                    name=name, mention=f"<#{next(channel_ids)}>"
                )
            ),
        )
        interaction = SimpleNamespace(guild=guild)
        return guild.create_text_channel, cast(discord.Interaction, interaction)

    async def test_create_times_logs_audit_for_created_channels(self) -> None:
        category = SimpleNamespace(
            name=TimesChannels.CATEGORY_NAME,
            text_channels=[SimpleNamespace(name="existing")],
        )
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
            await callback(self.cog, interaction, "Alpha, existing, Beta")

        self.assertEqual(create_text_channel.await_count, 2)
        create_text_channel.assert_any_await(name="alpha", category=category)
        create_text_channel.assert_any_await(name="beta", category=category)
        send_interaction.assert_awaited_once()
        log_audit.assert_awaited_once_with(
            self.bot,
            interaction,
            command_name="times create",
            details=["作成: <#101>, <#102>"],
        )


if __name__ == "__main__":
    unittest.main()
