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


class CloseCampaignResourcesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.db = Database(self.path)
        self.item = self.db.create_campaign(
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
        self.cog = CTFTeamCampaigns.__new__(CTFTeamCampaigns)
        self.cog.bot = mock.Mock()
        self.cog.settings = SimpleNamespace(tzinfo=datetime.UTC)
        self.cog.db = self.db

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            with suppress(FileNotFoundError):
                os.unlink(self.path + suffix)

    def make_guild(self) -> mock.Mock:
        guild = mock.Mock(spec=discord.Guild)
        channels = {
            2: mock.Mock(spec=discord.TextChannel),
            5: mock.Mock(spec=discord.TextChannel),
        }
        guild.get_channel.side_effect = channels.get
        guild.get_role.return_value = mock.Mock(spec=discord.Role)
        return guild

    async def test_first_close_sends_snapshot_once(self) -> None:
        mark = mock.AsyncMock(return_value=True)
        delete = mock.AsyncMock(return_value=True)
        snapshot = mock.AsyncMock(return_value=(0, True))
        with (
            mock.patch.object(discord_ops, "mark_message_closed", new=mark),
            mock.patch.object(discord_ops, "delete_voice_channel", new=delete),
            mock.patch.object(discord_ops, "send_close_snapshot", new=snapshot),
        ):
            result = await self.cog._close_campaign_resources(
                self.make_guild(), self.item
            )

        closed = self.db.find_closed_campaign_by_name(
            guild_id=1,
            ctf_name="Example",
        )
        assert closed is not None
        self.assertEqual(result, closed.archive_at_unix)
        snapshot.assert_awaited_once()

    async def test_retry_after_close_does_not_resend_snapshot(self) -> None:
        mark = mock.AsyncMock(return_value=True)
        delete = mock.AsyncMock(return_value=True)
        snapshot = mock.AsyncMock(return_value=(0, True))
        guild = self.make_guild()
        with (
            mock.patch.object(discord_ops, "mark_message_closed", new=mark),
            mock.patch.object(discord_ops, "delete_voice_channel", new=delete),
            mock.patch.object(discord_ops, "send_close_snapshot", new=snapshot),
        ):
            first_result = await self.cog._close_campaign_resources(guild, self.item)
            second_result = await self.cog._close_campaign_resources(guild, self.item)

        self.assertIsNotNone(first_result)
        self.assertIsNotNone(second_result)
        self.assertEqual(snapshot.await_count, 1)

    async def test_discord_failure_keeps_campaign_active(self) -> None:
        mark = mock.AsyncMock(return_value=False)
        delete = mock.AsyncMock(return_value=True)
        snapshot = mock.AsyncMock(return_value=(0, True))
        with (
            mock.patch.object(discord_ops, "mark_message_closed", new=mark),
            mock.patch.object(discord_ops, "delete_voice_channel", new=delete),
            mock.patch.object(discord_ops, "send_close_snapshot", new=snapshot),
        ):
            result = await self.cog._close_campaign_resources(
                self.make_guild(), self.item
            )

        self.assertIsNone(result)
        active = self.db.find_active_campaign_by_name(
            guild_id=1,
            ctf_name="Example",
        )
        self.assertIsNotNone(active)
        snapshot.assert_not_awaited()


class GuildRequirementTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_command_reports_service_error(self) -> None:
        cog = CTFTeamCampaigns.__new__(CTFTeamCampaigns)
        interaction = mock.Mock(spec=discord.Interaction)
        interaction.guild = None
        interaction.response = mock.Mock()
        interaction.response.defer = mock.AsyncMock()
        send = mock.AsyncMock()

        with mock.patch("bot.features.ctf_team.cog.send_interaction", new=send):
            await CTFTeamCampaigns.list_campaigns.callback(cog, interaction)
            send.assert_awaited_once_with(interaction, "サーバー内で実行してください。")
