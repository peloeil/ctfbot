from typing import Any, cast
from unittest import mock

import discord

from tests.ctfteam_support import (
    CATEGORY_ID,
    CREATOR_ID,
    ROLE_CHANNEL_ID,
    CTFTeamTestCase,
    http_error,
)

FUTURE_START = "2099-01-01 00:00"
PAST_START = "2000-01-01 00:00"


class OpenTestCase(CTFTeamTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.guild = mock.Mock(spec=discord.Guild)
        self.guild.id = 1
        self.guild.default_role = mock.Mock(spec=discord.Role)
        self.guild.me = mock.Mock(spec=discord.Member)

        self.category = mock.Mock(spec=discord.CategoryChannel)
        self.category.channels = []
        self.message = mock.Mock(spec=discord.Message, id=3)
        self.message.add_reaction = mock.AsyncMock()
        self.message.delete = mock.AsyncMock()
        self.role_channel = mock.Mock(spec=discord.TextChannel, id=ROLE_CHANNEL_ID)
        self.role_channel.send = mock.AsyncMock(return_value=self.message)
        channels = {CATEGORY_ID: self.category, ROLE_CHANNEL_ID: self.role_channel}
        self.guild.get_channel.side_effect = channels.get

        self.role = mock.Mock(spec=discord.Role, id=4, mention="<@&4>")
        self.role.members = []
        self.role.delete = mock.AsyncMock()
        self.discussion = mock.Mock(spec=discord.TextChannel, id=5, mention="<#5>")
        self.discussion.send = mock.AsyncMock()
        self.discussion.delete = mock.AsyncMock()
        self.voice = mock.Mock(spec=discord.VoiceChannel, id=6)
        self.voice.delete = mock.AsyncMock()
        self.guild.create_role = mock.AsyncMock(return_value=self.role)
        self.guild.create_text_channel = mock.AsyncMock(return_value=self.discussion)
        self.guild.create_voice_channel = mock.AsyncMock(return_value=self.voice)

        self.creator = mock.Mock(spec=discord.Member)
        self.creator.name = "creator"
        self.creator.roles = []
        self.creator.add_roles = mock.AsyncMock()
        self.guild.get_member.return_value = self.creator

        self.interaction = self.make_interaction(user_id=CREATOR_ID, guild=self.guild)

    async def submit(self, start_at: str = FUTURE_START, name: str = "Example") -> None:
        await self.cog.handle_create_submit(
            self.interaction, name, discord.Colour.blue(), start_at, ""
        )

    def assert_created_resources_deleted(self) -> None:
        for resource in (self.message, self.voice, self.discussion, self.role):
            with self.subTest(resource=resource):
                resource.delete.assert_awaited_once()

    def assert_nothing_created(self) -> None:
        self.guild.create_role.assert_not_awaited()
        self.assertIsNone(self.db.find_active_campaign_by_name(ctf_name="Example"))


class OpenCommandTest(OpenTestCase):
    async def open(self, color: str = "3b82f6") -> None:
        await cast(Any, self.cog.open_campaign).callback(
            self.cog, self.interaction, "Example", color
        )

    async def test_role_color_that_is_not_six_hex_digits_is_rejected(self) -> None:
        for value in ["#fff", "fff", "#1000000", "#-1", " #3b82f6", "#3b82g6"]:
            with self.subTest(value=value):
                self.interaction = self.make_interaction(guild=self.guild)

                await self.open(value)

                self.assert_replied_ephemerally(
                    self.interaction, "ロール色は #RRGGBB 形式で指定してください。"
                )
                self.interaction.response.send_modal.assert_not_awaited()

    async def test_unconfigured_feature_is_rejected_before_showing_modal(self) -> None:
        self.settings.ctfteam_category_id = None

        await self.open()

        self.assert_replied_ephemerally(
            self.interaction, "ctfteam 機能が設定されていません。"
        )
        self.interaction.response.send_modal.assert_not_awaited()

    async def test_six_hex_digit_color_without_prefix_opens_modal(self) -> None:
        await self.open("3b82f6")

        self.interaction.response.send_modal.assert_awaited_once()
        self.interaction.response.send_message.assert_not_awaited()


class OpenSuccessTest(OpenTestCase):
    async def test_success_records_campaign_with_created_resources(self) -> None:
        await self.submit()

        item = self.db.find_active_campaign_by_name(ctf_name="Example")
        assert item is not None
        self.assertEqual(
            (
                item.channel_id,
                item.message_id,
                item.role_id,
                item.discussion_channel_id,
                item.voice_channel_id,
                item.created_by,
            ),
            (ROLE_CHANNEL_ID, 3, 4, 5, 6, CREATOR_ID),
        )

    async def test_success_creates_mentionable_role_with_requested_name_and_color(
        self,
    ) -> None:
        await self.submit()

        self.guild.create_role.assert_awaited_once_with(
            name="Example", colour=discord.Colour.blue(), mentionable=True
        )

    async def test_recruitment_message_allows_only_role_mention_and_gets_reaction(
        self,
    ) -> None:
        await self.submit()

        mentions = self.role_channel.send.call_args.kwargs["allowed_mentions"]
        self.assertEqual(
            (mentions.everyone, mentions.users, mentions.roles),
            (False, False, [self.role]),
        )
        self.message.add_reaction.assert_awaited_once_with("✅")

    async def test_success_grants_role_to_creator_and_reports_creation(self) -> None:
        await self.submit()

        self.creator.add_roles.assert_awaited_once_with(self.role)
        self.assert_replied_ephemerally(
            self.interaction, "**Example** の募集を作成しました。"
        )
        self.assert_audited("ctfteam open")

    async def test_creator_who_already_has_role_is_not_granted_again(self) -> None:
        self.creator.roles = [self.role]

        await self.submit()

        self.creator.add_roles.assert_not_awaited()

    async def test_uncached_creator_is_not_granted_role_and_no_warning_is_shown(
        self,
    ) -> None:
        self.guild.get_member.return_value = None

        await self.submit()

        self.assert_replied_ephemerally(
            self.interaction, "**Example** の募集を作成しました。"
        )

    async def test_creator_role_grant_failure_keeps_campaign_and_warns(self) -> None:
        self.creator.add_roles.side_effect = http_error(discord.Forbidden, 403)

        with self.assertLogs("ctfbot", level="WARNING"):
            await self.submit()

        self.assertIsNotNone(self.db.find_active_campaign_by_name(ctf_name="Example"))
        self.assert_replied_ephemerally(
            self.interaction,
            "**Example** の募集を作成しました。\n"
            "⚠️ 作成者へのロール付与に失敗しました。"
            "募集メッセージに ✅ リアクションすると参加できます。",
        )
        self.role.delete.assert_not_awaited()
        self.assert_audited("ctfteam open")


class OpenStartNoticeTest(OpenTestCase):
    async def test_campaign_already_started_announces_start_immediately(self) -> None:
        await self.submit(start_at=PAST_START)

        self.discussion.send.assert_awaited_once()
        self.assertEqual(
            self.discussion.send.call_args.args[0], "🚀 **Example** が開始しました!"
        )

    async def test_immediate_announcement_is_not_repeated_by_start_loop(self) -> None:
        await self.submit(start_at=PAST_START)
        self.bot.get_guild.return_value = self.guild
        self.guild.get_role.return_value = self.role

        await self.cog.start_due_campaigns.coro(self.cog)

        self.discussion.send.assert_awaited_once()

    async def test_future_campaign_sends_no_start_announcement(self) -> None:
        await self.submit(start_at=FUTURE_START)

        self.discussion.send.assert_not_awaited()

    async def test_failed_immediate_announcement_does_not_undo_creation(self) -> None:
        self.discussion.send.side_effect = http_error(discord.HTTPException, 500)

        with self.assertLogs("ctfbot", level="WARNING"):
            await self.submit(start_at=PAST_START)

        self.assertIsNotNone(self.db.find_active_campaign_by_name(ctf_name="Example"))
        self.assert_replied_ephemerally(
            self.interaction, "**Example** の募集を作成しました。"
        )


class OpenFailureTest(OpenTestCase):
    async def test_invalid_datetime_is_reported_without_creating_resources(
        self,
    ) -> None:
        await self.submit(start_at="bad")

        self.assert_replied_ephemerally(
            self.interaction,
            "開始/終了日時の形式が不正です。YYYY-MM-DD HH:MM 形式で入力してください。",
        )
        self.assert_nothing_created()

    async def test_duplicate_active_name_is_rejected_without_creating_resources(
        self,
    ) -> None:
        self.create_active("example", created_by=8)

        await self.submit()

        self.assert_replied_ephemerally(
            self.interaction,
            "同名の active 募集が既に存在します。"
            "別名を使うか既存募集を close してください。",
        )
        self.guild.create_role.assert_not_awaited()

    async def test_missing_category_is_reported_without_creating_resources(
        self,
    ) -> None:
        self.guild.get_channel.side_effect = {ROLE_CHANNEL_ID: self.role_channel}.get

        await self.submit()

        self.assert_replied_ephemerally(
            self.interaction, "CTF募集カテゴリが見つかりません。"
        )
        self.assert_nothing_created()

    async def test_conflict_at_insert_deletes_created_resources_and_reports_it(
        self,
    ) -> None:
        # Another creator takes the name between the pre-check and the insert.
        async def create_role_while_rival_claims_name(**_: object) -> Any:
            self.create_active("Example", created_by=8)
            return self.role

        self.guild.create_role.side_effect = create_role_while_rival_claims_name

        await self.submit()

        self.assert_replied_ephemerally(
            self.interaction,
            "同名の募集が作成されたか、active 募集数の上限に達しました。",
        )
        self.assert_created_resources_deleted()
        self.assertEqual(self.db.count_active_campaigns_by_creator(CREATOR_ID), 0)
        self.assert_not_audited()

    async def test_unexpected_error_deletes_created_resources_and_reports_it(
        self,
    ) -> None:
        self.role_channel.send.side_effect = RuntimeError("boom")
        self.message.delete.side_effect = AssertionError("message was never sent")

        with self.assertLogs("ctfbot", level="ERROR"):
            await self.submit()

        self.assert_replied_ephemerally(
            self.interaction, "募集の作成中にエラーが発生しました。"
        )
        self.voice.delete.assert_awaited_once()
        self.discussion.delete.assert_awaited_once()
        self.role.delete.assert_awaited_once()
        self.message.delete.assert_not_awaited()
        self.assertIsNone(self.db.find_active_campaign_by_name(ctf_name="Example"))
        self.assert_not_audited()

    async def test_failure_midway_deletes_only_what_was_created(self) -> None:
        self.guild.create_text_channel.side_effect = http_error(
            discord.HTTPException, 500
        )

        with self.assertLogs("ctfbot", level="ERROR"):
            await self.submit()

        self.role.delete.assert_awaited_once()
        self.voice.delete.assert_not_awaited()
        self.discussion.delete.assert_not_awaited()
        self.assert_replied_ephemerally(
            self.interaction, "募集の作成中にエラーが発生しました。"
        )


class StartDueCampaignsTest(OpenTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.item = self.create_active(start_at_unix=0)
        self.bot.get_guild.return_value = self.guild
        self.guild.get_channel.side_effect = {5: self.discussion}.get
        self.guild.get_role.return_value = self.role

    async def run_task(self) -> None:
        await self.cog.start_due_campaigns.coro(self.cog)

    async def test_due_campaign_is_announced_once_across_runs(self) -> None:
        await self.run_task()
        await self.run_task()

        self.discussion.send.assert_awaited_once()
        self.assertEqual(
            self.discussion.send.call_args.args[0], "🚀 **Example** が開始しました!"
        )

    async def test_unresolved_resources_leave_start_notification_pending(
        self,
    ) -> None:
        self.guild.get_channel.side_effect = {}.get
        self.guild.get_role.return_value = None

        with self.assertLogs("ctfbot", level="WARNING"):
            await self.run_task()

        self.assertEqual(
            [item.id for item in self.db.list_due_starts(10**10)], [self.item.id]
        )

    async def test_missing_guild_leaves_start_notification_pending(self) -> None:
        self.bot.get_guild.return_value = None

        with self.assertLogs("ctfbot", level="WARNING"):
            await self.run_task()

        self.assertEqual(
            [item.id for item in self.db.list_due_starts(10**10)], [self.item.id]
        )

    async def test_closed_campaign_is_not_announced(self) -> None:
        self.db.close_campaign(self.item.id, 201, 300)

        await self.run_task()

        self.discussion.send.assert_not_awaited()
