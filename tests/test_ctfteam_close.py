from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import discord

from ctfbot.features.ctfteam import discord_ops
from ctfbot.helpers import format_timestamp_with_relative
from tests.ctfteam_support import CTFTeamTestCase, http_error


class CloseTestCase(CTFTeamTestCase):
    def make_guild(self) -> Any:
        guild = mock.Mock(spec=discord.Guild)
        self.recruit_message = mock.Mock(spec=discord.Message)
        self.recruit_message.content = "Original"
        self.recruit_message.edit = mock.AsyncMock()
        self.recruit_channel = mock.Mock(spec=discord.TextChannel)
        self.recruit_channel.fetch_message = mock.AsyncMock(
            return_value=self.recruit_message
        )
        self.discussion = mock.Mock(spec=discord.TextChannel)
        self.discussion.send = mock.AsyncMock()
        self.voice = mock.Mock(spec=discord.VoiceChannel)
        self.voice.delete = mock.AsyncMock()
        channels = {9: self.recruit_channel, 5: self.discussion, 6: self.voice}
        guild.get_channel.side_effect = channels.get
        self.role = mock.Mock(spec=discord.Role)
        self.role.members = [SimpleNamespace(mention="<@11>")]
        guild.get_role.return_value = self.role
        return guild

    async def close(self, interaction: Any, name: str = "Example") -> None:
        await cast(Any, self.cog.close_campaign_cmd).callback(
            self.cog, interaction, name
        )


class CloseCommandTest(CloseTestCase):
    async def test_creator_closes_campaign_and_receives_archive_schedule(self) -> None:
        self.create_active()
        interaction = self.make_interaction(guild=self.make_guild())

        await self.close(interaction)

        closed = self.db.find_closed_campaign_by_name(ctf_name="Example")
        assert closed is not None
        self.assert_replied_ephemerally(
            interaction,
            "**Example** を終了しました。archive 予定: "
            f"{format_timestamp_with_relative(closed.archive_at_unix)}",
        )
        self.assert_audited("ctfteam close")

    async def test_close_stops_recruitment_and_leaves_participant_snapshot(
        self,
    ) -> None:
        self.create_active()
        interaction = self.make_interaction(guild=self.make_guild())

        await self.close(interaction)

        edited = self.recruit_message.edit.call_args.kwargs["content"]
        self.assertTrue(edited.startswith(discord_ops.CLOSED_HEADER))
        self.voice.delete.assert_awaited_once()
        self.assertEqual(
            [call.args[0] for call in self.discussion.send.await_args_list],
            ["🔒 **Example** の募集が終了しました。\n参加メンバー (1人):", "<@11>"],
        )

    async def test_manage_guild_member_can_close_others_campaign(self) -> None:
        self.create_active(created_by=7)
        interaction = self.make_interaction(
            user_id=8, manage_guild=True, guild=self.make_guild()
        )

        await self.close(interaction)

        self.assertIsNotNone(self.db.find_closed_campaign_by_name(ctf_name="Example"))

    async def test_member_without_manage_guild_cannot_close_others_campaign(
        self,
    ) -> None:
        self.create_active(created_by=7)
        interaction = self.make_interaction(user_id=8, guild=self.make_guild())

        await self.close(interaction)

        self.assert_replied_ephemerally(
            interaction, "この募集を終了する権限がありません。"
        )
        self.assertIsNotNone(self.db.find_active_campaign_by_name(ctf_name="Example"))
        self.voice.delete.assert_not_awaited()
        self.assert_not_audited()

    async def test_unknown_campaign_name_is_reported(self) -> None:
        interaction = self.make_interaction(guild=self.make_guild())

        await self.close(interaction, "Nope")

        self.assert_replied_ephemerally(
            interaction, "active 募集 'Nope' が見つかりません。"
        )
        self.assert_not_audited()

    async def test_name_with_surrounding_spaces_matches_campaign(self) -> None:
        self.create_active()
        interaction = self.make_interaction(guild=self.make_guild())

        await self.close(interaction, "  Example  ")

        self.assertIsNotNone(self.db.find_closed_campaign_by_name(ctf_name="Example"))

    async def test_discord_failure_keeps_campaign_active_and_skips_snapshot(
        self,
    ) -> None:
        self.create_active()
        interaction = self.make_interaction(guild=self.make_guild())
        self.voice.delete.side_effect = http_error(discord.Forbidden, 403)

        with self.assertLogs("ctfbot", level="WARNING"):
            await self.close(interaction)

        self.assert_replied_ephemerally(
            interaction,
            "Discord リソースの更新に失敗したため、募集を終了しませんでした。",
        )
        self.assertIsNotNone(self.db.find_active_campaign_by_name(ctf_name="Example"))
        self.discussion.send.assert_not_awaited()
        self.assert_not_audited()

    async def test_losing_close_race_still_succeeds_without_second_snapshot(
        self,
    ) -> None:
        item = self.create_active()
        interaction = self.make_interaction(guild=self.make_guild())
        # The automatic close wins the DB claim while this command works on Discord.
        self.voice.delete.side_effect = lambda: self.db.close_campaign(
            item.id, 201, 300
        )

        await self.close(interaction)

        interaction.followup.send.assert_awaited_once()
        self.assertTrue(
            interaction.followup.send.call_args.args[0].startswith(
                "**Example** を終了しました。"
            )
        )
        self.discussion.send.assert_not_awaited()

    async def test_command_outside_guild_asks_to_run_in_guild(self) -> None:
        self.create_active()
        interaction = self.make_interaction(guild=None)

        await self.close(interaction)

        self.assert_replied_ephemerally(interaction, "サーバー内で実行してください。")
        self.assertIsNotNone(self.db.find_active_campaign_by_name(ctf_name="Example"))


class CloseExpiredCampaignsLoopTest(CloseTestCase):
    async def run_loop(self) -> None:
        await self.cog.close_expired_campaigns.coro(self.cog)

    async def test_only_campaigns_past_their_end_are_closed(self) -> None:
        self.create_active("Expired", end_at_unix=200, message_id=3)
        self.create_active("Ongoing", end_at_unix=10**10, message_id=4)
        self.create_active("Permanent", end_at_unix=None, message_id=5)
        self.bot.get_guild.return_value = self.make_guild()

        await self.run_loop()

        self.assertIsNotNone(self.db.find_closed_campaign_by_name(ctf_name="Expired"))
        for name in ("Ongoing", "Permanent"):
            with self.subTest(name=name):
                self.assertIsNotNone(
                    self.db.find_active_campaign_by_name(ctf_name=name)
                )

    async def test_missing_guild_leaves_expired_campaign_active_for_retry(self) -> None:
        self.create_active(end_at_unix=200)
        self.bot.get_guild.return_value = None

        await self.run_loop()

        self.assertIsNotNone(self.db.find_active_campaign_by_name(ctf_name="Example"))

    async def test_closing_twice_sends_snapshot_once(self) -> None:
        self.create_active(end_at_unix=200)
        self.bot.get_guild.return_value = self.make_guild()

        await self.run_loop()
        await self.run_loop()

        header_sends = [
            call
            for call in self.discussion.send.await_args_list
            if "募集が終了しました" in call.args[0]
        ]
        self.assertEqual(len(header_sends), 1)
