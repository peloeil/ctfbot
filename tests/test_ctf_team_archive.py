import datetime
import os
import tempfile
import unittest
from contextlib import suppress
from types import SimpleNamespace
from unittest import mock

import discord

from bot.db import Database
from bot.features.ctf_team import discord_ops
from bot.features.ctf_team.cog import CTFTeamCampaigns


class ArchiveCampaignResourcesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.db = Database(self.path)
        active = self.db.create_campaign(
            guild_id=1,
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
            guild_id=1,
            ctf_name="Example",
        )
        assert item is not None
        self.item = item
        self.cog = CTFTeamCampaigns.__new__(CTFTeamCampaigns)
        self.cog.bot = mock.Mock()
        self.cog.settings = SimpleNamespace(
            tzinfo=datetime.UTC,
            ctf_team_archive_category_id=8,
        )
        self.cog.db = self.db

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            with suppress(FileNotFoundError):
                os.unlink(self.path + suffix)

    def make_guild(
        self,
    ) -> tuple[
        mock.Mock,
        mock.Mock,
        mock.Mock,
        mock.Mock,
    ]:
        guild = mock.Mock(spec=discord.Guild)
        archive_category = mock.Mock(spec=discord.CategoryChannel)
        discussion = mock.Mock(spec=discord.TextChannel)
        discussion.guild = guild
        discussion.overwrites_for.return_value = discord.PermissionOverwrite()
        discussion.set_permissions = mock.AsyncMock()
        discussion.edit = mock.AsyncMock()
        discussion.send = mock.AsyncMock()
        role = mock.Mock(spec=discord.Role)
        role.delete = mock.AsyncMock()
        channels = {5: discussion, 8: archive_category}
        guild.get_channel.side_effect = channels.get
        guild.get_role.return_value = role
        guild.me = mock.Mock(spec=discord.Member)
        guild.default_role = mock.Mock(spec=discord.Role)
        return guild, archive_category, discussion, role

    async def test_resource_failure_does_not_send_archive_notification(self) -> None:
        guild, _, discussion, _ = self.make_guild()
        delete_voice = mock.AsyncMock(return_value=False)

        with mock.patch.object(discord_ops, "delete_voice_channel", new=delete_voice):
            result = await self.cog._archive_campaign_resources(guild, self.item)

        self.assertFalse(result)
        discussion.send.assert_not_awaited()
        archived = self.db.find_closed_campaign_by_name(
            guild_id=1,
            ctf_name="Example",
            archived=True,
        )
        self.assertIsNone(archived)

    async def test_failed_archive_claim_does_not_send_notification(self) -> None:
        guild, _, discussion, _ = self.make_guild()
        self.db.mark_archived(self.item.id, 301)
        delete_voice = mock.AsyncMock(return_value=True)

        with mock.patch.object(discord_ops, "delete_voice_channel", new=delete_voice):
            result = await self.cog._archive_campaign_resources(guild, self.item)

        self.assertTrue(result)
        discussion.send.assert_not_awaited()

    async def test_notification_failure_keeps_archived_state(self) -> None:
        guild, _, discussion, _ = self.make_guild()
        delete_voice = mock.AsyncMock(return_value=True)
        send = mock.AsyncMock(return_value=None)

        with (
            mock.patch.object(discord_ops, "delete_voice_channel", new=delete_voice),
            mock.patch("bot.features.ctf_team.cog.send_safely", new=send),
        ):
            result = await self.cog._archive_campaign_resources(guild, self.item)

        self.assertTrue(result)
        send.assert_awaited_once_with(
            discussion,
            "📦 このチャンネルは archive カテゴリに移動されました。",
        )
        archived = self.db.find_closed_campaign_by_name(
            guild_id=1,
            ctf_name="Example",
            archived=True,
        )
        assert archived is not None
        self.assertIsNotNone(archived.archived_at_unix)
        self.assertEqual(self.db.list_due_archives(10**10), [])
