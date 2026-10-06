import datetime
import os
import tempfile
import unittest
from contextlib import suppress
from types import SimpleNamespace
from typing import Any
from unittest import mock

import discord

from ctfbot.db import Database
from ctfbot.features.ctfteam import discord_ops
from ctfbot.features.ctfteam.cog import CTFTeamCampaigns


class ArchiveCampaignResourcesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.db = Database(self.path)
        active = self.db.create_campaign(
            channel_id=2,
            message_id=3,
            role_id=4,
            discussion_channel_id=5,
            voice_channel_id=6,
            ctf_name="Example",
            start_at_unix=100,
            end_at_unix=200,
            created_by=7,
            created_at_unix=90,
            max_active_per_creator=5,
        )
        self.db.close_campaign(active.id, 201, 300)
        item = self.db.find_closed_campaign_by_name(
            ctf_name="Example",
        )
        assert item is not None
        self.item = item
        self.cog: Any = CTFTeamCampaigns.__new__(CTFTeamCampaigns)
        self.cog.bot = mock.Mock()
        self.cog.settings = SimpleNamespace(
            tzinfo=datetime.UTC,
            ctfteam_archive_category_id=8,
        )
        self.cog.db = self.db

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            with suppress(FileNotFoundError):
                os.unlink(self.path + suffix)

    def make_guild(
        self,
        *,
        creator_cached: bool = True,
    ) -> tuple[
        mock.Mock,
        mock.Mock,
        mock.Mock,
    ]:
        guild = mock.Mock(spec=discord.Guild)
        archive_category = mock.Mock(spec=discord.CategoryChannel)
        discussion = mock.Mock(spec=discord.TextChannel)
        discussion.guild = guild
        discussion.edit = mock.AsyncMock()
        discussion.send = mock.AsyncMock()
        role = mock.Mock(spec=discord.Role, id=4)
        role.delete = mock.AsyncMock()
        channels = {5: discussion, 8: archive_category}
        guild.get_channel.side_effect = channels.get
        guild.get_role.return_value = role
        guild.me = mock.Mock(spec=discord.Member, id=9)
        guild.default_role = mock.Mock(spec=discord.Role, id=1)
        creator = mock.Mock(spec=discord.Member, id=self.item.created_by)
        discussion.overwrites = discord_ops._text_overwrites(
            guild, role, creator, guild.me
        )
        if not creator_cached:
            discussion.overwrites[discord.Object(id=creator.id, type=discord.User)] = (
                discussion.overwrites.pop(creator)
            )
        discussion.overwrites_for.side_effect = discussion.overwrites.__getitem__
        return guild, discussion, role

    async def test_archive_removes_creator_and_role_overwrites(self) -> None:
        for creator_cached in (True, False):
            with self.subTest(creator_cached=creator_cached):
                guild, discussion, role = self.make_guild(creator_cached=creator_cached)
                delete_voice = mock.AsyncMock(return_value=True)
                with mock.patch.object(
                    discord_ops, "delete_voice_channel", new=delete_voice
                ):
                    result = await self.cog._archive_campaign_resources(
                        guild, self.item
                    )

                self.assertTrue(result)
                discussion.edit.assert_awaited_once()
                overwrites = discussion.edit.call_args.kwargs["overwrites"]
                self.assertNotIn(
                    self.item.created_by, {target.id for target in overwrites}
                )
                self.assertNotIn(role, overwrites)
                self.assertTrue(overwrites[guild.default_role].view_channel)
                self.assertFalse(overwrites[guild.default_role].send_messages)
                self.assertFalse(overwrites[guild.default_role].create_public_threads)
                self.assertFalse(overwrites[guild.default_role].create_private_threads)
                self.assertFalse(
                    overwrites[guild.default_role].send_messages_in_threads
                )
                self.assertFalse(overwrites[guild.default_role].send_voice_messages)
                self.assertFalse(overwrites[guild.default_role].send_polls)
                self.assertTrue(overwrites[guild.me].send_messages)
                self.assertTrue(overwrites[guild.me].manage_channels)

    async def test_permission_update_failure_keeps_campaign_unarchived(self) -> None:
        guild, discussion, _ = self.make_guild()
        discussion.edit.side_effect = discord.Forbidden(
            mock.Mock(status=403, reason="Forbidden"), "cannot edit channel"
        )
        delete_voice = mock.AsyncMock(return_value=True)
        with mock.patch.object(discord_ops, "delete_voice_channel", new=delete_voice):
            result = await self.cog._archive_campaign_resources(guild, self.item)

        self.assertFalse(result)
        discussion.send.assert_not_awaited()
        self.assertIsNone(
            self.db.find_closed_campaign_by_name(ctf_name="Example", archived=True)
        )

    async def test_resource_failure_does_not_send_archive_notification(self) -> None:
        guild, discussion, _ = self.make_guild()
        delete_voice = mock.AsyncMock(return_value=False)

        with mock.patch.object(discord_ops, "delete_voice_channel", new=delete_voice):
            result = await self.cog._archive_campaign_resources(guild, self.item)

        self.assertFalse(result)
        discussion.send.assert_not_awaited()
        archived = self.db.find_closed_campaign_by_name(
            ctf_name="Example",
            archived=True,
        )
        self.assertIsNone(archived)

    async def test_role_delete_not_found_is_treated_as_success(self) -> None:
        guild, _, role = self.make_guild()
        role.delete.side_effect = discord.NotFound(
            mock.Mock(status=404, reason="Not Found"), "missing role"
        )
        delete_voice = mock.AsyncMock(return_value=True)

        with mock.patch.object(discord_ops, "delete_voice_channel", new=delete_voice):
            result = await self.cog._archive_campaign_resources(guild, self.item)

        self.assertTrue(result)
        archived = self.db.find_closed_campaign_by_name(
            ctf_name="Example",
            archived=True,
        )
        self.assertIsNotNone(archived)

    async def test_failed_archive_claim_does_not_send_notification(self) -> None:
        guild, discussion, _ = self.make_guild()
        self.db.mark_archived(self.item.id, 301)
        delete_voice = mock.AsyncMock(return_value=True)

        with mock.patch.object(discord_ops, "delete_voice_channel", new=delete_voice):
            result = await self.cog._archive_campaign_resources(guild, self.item)

        self.assertTrue(result)
        discussion.send.assert_not_awaited()

    async def test_notification_failure_keeps_archived_state(self) -> None:
        guild, discussion, _ = self.make_guild()
        delete_voice = mock.AsyncMock(return_value=True)
        send = mock.AsyncMock(return_value=None)

        with (
            mock.patch.object(discord_ops, "delete_voice_channel", new=delete_voice),
            mock.patch("ctfbot.features.ctfteam.cog.send_safely", new=send),
        ):
            result = await self.cog._archive_campaign_resources(guild, self.item)

        self.assertTrue(result)
        send.assert_awaited_once_with(
            discussion,
            "📦 このチャンネルは archive カテゴリに移動されました。",
        )
        archived = self.db.find_closed_campaign_by_name(
            ctf_name="Example",
            archived=True,
        )
        assert archived is not None
        self.assertIsNotNone(archived.archived_at_unix)
        self.assertEqual(self.db.list_due_archives(10**10), [])
