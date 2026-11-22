from typing import Any, cast
from unittest import mock

import discord

from tests.ctfteam_support import (
    ARCHIVE_CATEGORY_ID,
    CREATOR_ID,
    CTFTeamTestCase,
    http_error,
)

ARCHIVED_NOTICE = "📦 このチャンネルは archive カテゴリに移動されました。"


class ArchiveTestCase(CTFTeamTestCase):
    def make_guild(self, *, creator_cached: bool = True) -> Any:
        guild = mock.Mock(spec=discord.Guild)
        guild.default_role = mock.Mock(spec=discord.Role, id=1)
        guild.me = mock.Mock(spec=discord.Member, id=9)
        self.archive_category = mock.Mock(spec=discord.CategoryChannel)
        self.voice = mock.Mock(spec=discord.VoiceChannel)
        self.voice.delete = mock.AsyncMock()
        self.discussion = mock.Mock(spec=discord.TextChannel)
        self.discussion.guild = guild
        self.discussion.edit = mock.AsyncMock()
        self.discussion.send = mock.AsyncMock()
        self.role = mock.Mock(spec=discord.Role, id=4)
        self.role.delete = mock.AsyncMock()
        channels = {
            5: self.discussion,
            6: self.voice,
            ARCHIVE_CATEGORY_ID: self.archive_category,
        }
        guild.get_channel.side_effect = channels.get
        guild.get_role.return_value = self.role

        creator: Any = (
            mock.Mock(spec=discord.Member, id=CREATOR_ID)
            if creator_cached
            else discord.Object(id=CREATOR_ID, type=discord.User)
        )
        member_access = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        )
        self.discussion.overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            self.role: member_access,
            creator: member_access,
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
        }
        self.discussion.overwrites_for.side_effect = (
            self.discussion.overwrites.__getitem__
        )
        return guild

    async def archive(self, interaction: Any, name: str = "Example") -> None:
        await cast(Any, self.cog.archive_campaign_cmd).callback(
            self.cog, interaction, name
        )

    def archived(self) -> Any:
        return self.db.find_closed_campaign_by_name(ctf_name="Example", archived=True)

    def new_overwrites(self) -> dict[Any, discord.PermissionOverwrite]:
        return self.discussion.edit.call_args.kwargs["overwrites"]


class ArchiveCommandTest(ArchiveTestCase):
    async def test_archive_moves_channel_and_cleans_up_resources(self) -> None:
        self.create_closed()
        interaction = self.make_interaction(guild=self.make_guild())

        await self.archive(interaction)

        self.assert_replied_ephemerally(
            interaction, "**Example** を archive しました。"
        )
        self.assertIs(
            self.discussion.edit.call_args.kwargs["category"], self.archive_category
        )
        self.voice.delete.assert_awaited_once()
        self.role.delete.assert_awaited_once()
        self.assertIsNotNone(self.archived())
        self.discussion.send.assert_awaited_once_with(ARCHIVED_NOTICE)
        self.assert_audited("ctfteam archive")

    async def test_archived_channel_is_read_only_for_everyone(self) -> None:
        self.create_closed()
        guild = self.make_guild()

        await self.archive(self.make_interaction(guild=guild))

        everyone = self.new_overwrites()[guild.default_role]
        self.assertTrue(everyone.view_channel)
        self.assertTrue(everyone.read_message_history)
        for denied in (
            "send_messages",
            "add_reactions",
            "create_public_threads",
            "create_private_threads",
            "send_messages_in_threads",
            "send_voice_messages",
            "send_polls",
        ):
            with self.subTest(permission=denied):
                self.assertIs(getattr(everyone, denied), False)

    async def test_bot_keeps_posting_and_can_manage_archived_channel(self) -> None:
        self.create_closed()
        guild = self.make_guild()

        await self.archive(self.make_interaction(guild=guild))

        bot_overwrite = self.new_overwrites()[guild.me]
        self.assertTrue(bot_overwrite.send_messages)
        self.assertTrue(bot_overwrite.manage_channels)

    async def test_role_and_cached_creator_overwrites_are_removed(self) -> None:
        self.create_closed()
        guild = self.make_guild(creator_cached=True)

        await self.archive(self.make_interaction(guild=guild))

        overwrites = self.new_overwrites()
        self.assertNotIn(self.role, overwrites)
        self.assertNotIn(CREATOR_ID, {target.id for target in overwrites})

    async def test_uncached_creator_overwrite_is_removed_by_stored_id(self) -> None:
        self.create_closed()
        guild = self.make_guild(creator_cached=False)

        await self.archive(self.make_interaction(guild=guild))

        self.assertNotIn(CREATOR_ID, {target.id for target in self.new_overwrites()})

    async def test_manage_guild_member_can_archive_others_campaign(self) -> None:
        self.create_closed(created_by=CREATOR_ID)
        interaction = self.make_interaction(
            user_id=8, manage_guild=True, guild=self.make_guild()
        )

        await self.archive(interaction)

        self.assertIsNotNone(self.archived())

    async def test_member_without_manage_guild_cannot_archive_others_campaign(
        self,
    ) -> None:
        self.create_closed(created_by=CREATOR_ID)
        interaction = self.make_interaction(user_id=8, guild=self.make_guild())

        await self.archive(interaction)

        self.assert_replied_ephemerally(
            interaction, "この募集を archive する権限がありません。"
        )
        self.discussion.edit.assert_not_awaited()
        self.assertIsNone(self.archived())
        self.assert_not_audited()

    async def test_active_campaign_is_directed_to_close_first(self) -> None:
        self.create_active()
        interaction = self.make_interaction(guild=self.make_guild())

        await self.archive(interaction)

        self.assert_replied_ephemerally(
            interaction,
            "'Example' は募集中です。先に `/ctfteam close` で終了してください。",
        )
        self.discussion.edit.assert_not_awaited()

    async def test_already_archived_campaign_is_reported(self) -> None:
        item = self.create_closed()
        self.db.mark_archived(item.id, 301)
        interaction = self.make_interaction(guild=self.make_guild())

        await self.archive(interaction)

        self.assert_replied_ephemerally(
            interaction, "'Example' は既に archive 済みです。"
        )
        self.discussion.edit.assert_not_awaited()

    async def test_unknown_campaign_name_is_reported(self) -> None:
        interaction = self.make_interaction(guild=self.make_guild())

        await self.archive(interaction, "Nope")

        self.assert_replied_ephemerally(interaction, "募集 'Nope' が見つかりません。")

    async def test_permission_update_failure_keeps_campaign_unarchived(self) -> None:
        self.create_closed()
        interaction = self.make_interaction(guild=self.make_guild())
        self.discussion.edit.side_effect = http_error(discord.Forbidden, 403)

        with self.assertLogs("ctfbot", level="WARNING"):
            await self.archive(interaction)

        self.assert_replied_ephemerally(
            interaction,
            "Discord リソースの archive に失敗したため、DB状態を更新しませんでした。",
        )
        self.assertIsNone(self.archived())
        self.discussion.send.assert_not_awaited()
        self.assert_not_audited()

    async def test_voice_delete_failure_keeps_campaign_unarchived(self) -> None:
        self.create_closed()
        interaction = self.make_interaction(guild=self.make_guild())
        self.voice.delete.side_effect = http_error(discord.Forbidden, 403)

        with self.assertLogs("ctfbot", level="WARNING"):
            await self.archive(interaction)

        self.assertIsNone(self.archived())
        self.discussion.send.assert_not_awaited()

    async def test_missing_archive_category_keeps_campaign_unarchived(self) -> None:
        self.create_closed()
        guild = self.make_guild()
        guild.get_channel.side_effect = {5: self.discussion}.get
        interaction = self.make_interaction(guild=guild)

        with self.assertLogs("ctfbot", level="WARNING"):
            await self.archive(interaction)

        self.assertIsNone(self.archived())
        self.discussion.edit.assert_not_awaited()

    async def test_already_deleted_role_counts_as_success(self) -> None:
        self.create_closed()
        interaction = self.make_interaction(guild=self.make_guild())
        self.role.delete.side_effect = http_error(discord.NotFound, 404)

        await self.archive(interaction)

        self.assertIsNotNone(self.archived())

    async def test_losing_archive_race_still_succeeds_without_notification(
        self,
    ) -> None:
        item = self.create_closed()
        interaction = self.make_interaction(guild=self.make_guild())
        # The automatic archive wins the DB claim while this command works on Discord.
        self.voice.delete.side_effect = lambda: self.db.mark_archived(item.id, 301)

        await self.archive(interaction)

        self.assert_replied_ephemerally(
            interaction, "**Example** を archive しました。"
        )
        self.discussion.send.assert_not_awaited()

    async def test_notification_failure_keeps_campaign_archived(self) -> None:
        self.create_closed()
        interaction = self.make_interaction(guild=self.make_guild())
        self.discussion.send.side_effect = http_error(discord.HTTPException, 500)

        with self.assertLogs("ctfbot", level="ERROR"):
            await self.archive(interaction)

        self.assert_replied_ephemerally(
            interaction, "**Example** を archive しました。"
        )
        self.assertIsNotNone(self.archived())
        self.assertEqual(self.db.list_due_archives(10**10), [])

    async def test_command_outside_guild_asks_to_run_in_guild(self) -> None:
        self.create_closed()
        interaction = self.make_interaction(guild=None)

        await self.archive(interaction)

        self.assert_replied_ephemerally(interaction, "サーバー内で実行してください。")
        self.assertIsNone(self.archived())


class ArchiveClosedCampaignsLoopTest(ArchiveTestCase):
    async def test_only_campaigns_past_their_archive_time_are_archived(self) -> None:
        self.create_closed("Due", archive_at_unix=300, message_id=3)
        self.create_closed("Waiting", archive_at_unix=10**10, message_id=4)
        self.bot.get_guild.return_value = self.make_guild()

        await self.cog.archive_closed_campaigns.coro(self.cog)

        due = self.db.find_closed_campaign_by_name(ctf_name="Due", archived=True)
        waiting = self.db.find_closed_campaign_by_name(
            ctf_name="Waiting", archived=False
        )
        self.assertIsNotNone(due)
        self.assertIsNotNone(waiting)

    async def test_failed_archive_is_retried_on_next_run(self) -> None:
        self.create_closed()
        self.bot.get_guild.return_value = self.make_guild()
        self.discussion.edit.side_effect = http_error(discord.Forbidden, 403)
        with self.assertLogs("ctfbot", level="WARNING"):
            await self.cog.archive_closed_campaigns.coro(self.cog)
        self.assertIsNone(self.archived())

        self.discussion.edit.side_effect = None
        await self.cog.archive_closed_campaigns.coro(self.cog)

        self.assertIsNotNone(self.archived())
