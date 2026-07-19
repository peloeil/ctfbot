import datetime
import os
import tempfile
import unittest
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import discord

from bot.db import Database
from bot.errors import ServiceError
from bot.features.ctf_team import discord_ops
from bot.features.ctf_team.cog import CTFTeamCampaigns


class OpenCampaignTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.db = Database(self.path)
        self.cog = CTFTeamCampaigns.__new__(CTFTeamCampaigns)
        self.cog.bot = mock.Mock()
        self.cog.settings = SimpleNamespace(
            tzinfo=datetime.UTC,
            ctf_team_category_id=8,
            ctf_team_role_channel_id=9,
        )
        self.cog.db = self.db

        self.interaction = mock.Mock(spec=discord.Interaction)
        self.interaction.user = SimpleNamespace(id=7)
        self.interaction.response = mock.Mock()
        self.interaction.response.defer = mock.AsyncMock()

        self.guild = mock.Mock(spec=discord.Guild)
        self.guild.id = 1
        self.interaction.guild = self.guild
        self.category = mock.Mock(spec=discord.CategoryChannel)
        self.role_channel = mock.Mock(spec=discord.TextChannel)
        self.role_channel.id = 2
        self.role = mock.Mock(spec=discord.Role)
        self.role.id = 4
        self.discussion = mock.Mock(spec=discord.TextChannel)
        self.discussion.id = 5
        self.voice = mock.Mock(spec=discord.VoiceChannel)
        self.voice.id = 6
        self.message = mock.Mock(spec=discord.Message)
        self.message.id = 3
        self.message.add_reaction = mock.AsyncMock()
        self.role_channel.send = mock.AsyncMock(return_value=self.message)
        self.guild.create_role = mock.AsyncMock(return_value=self.role)
        self.creator = mock.Mock(spec=discord.Member)
        self.creator.roles = []
        self.creator.add_roles = mock.AsyncMock()
        self.guild.get_member.return_value = self.creator
        self.guild.me = mock.Mock(spec=discord.Member)

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            with suppress(FileNotFoundError):
                os.unlink(self.path + suffix)

    async def submit(self) -> None:
        await self.cog.handle_create_submit(
            self.interaction,
            "Example",
            discord.Colour.blue(),
            "2099-01-01 00:00",
            "",
        )

    async def test_open_rejects_role_color_that_is_not_six_hex_digits(self) -> None:
        self.interaction.response.send_modal = mock.AsyncMock()
        send = mock.AsyncMock()
        invalid_values = ["#fff", "fff", "#1000000", "#-1", " #3b82f6", "#3b82g6"]

        with mock.patch("bot.features.ctf_team.cog.send_interaction", new=send):
            callback = cast(Any, self.cog.open_campaign.callback)
            for value in invalid_values:
                await callback(self.cog, self.interaction, "Example", value)

        self.assertEqual(send.await_count, len(invalid_values))
        send.assert_awaited_with(
            self.interaction, "ロール色は #RRGGBB 形式で指定してください。"
        )
        self.interaction.response.send_modal.assert_not_awaited()

    async def test_open_accepts_six_hex_digit_color_without_prefix(self) -> None:
        self.interaction.response.send_modal = mock.AsyncMock()
        send = mock.AsyncMock()

        with mock.patch("bot.features.ctf_team.cog.send_interaction", new=send):
            callback = cast(Any, self.cog.open_campaign.callback)
            await callback(self.cog, self.interaction, "Example", "3b82f6")

        send.assert_not_awaited()
        self.interaction.response.send_modal.assert_awaited_once()

    async def test_creator_role_forbidden_returns_warning_without_cleanup(
        self,
    ) -> None:
        response = mock.Mock(status=403, reason="Forbidden")
        self.creator.add_roles.side_effect = discord.Forbidden(response, "forbidden")
        cleanup = mock.AsyncMock()
        send = mock.AsyncMock()
        audit = mock.AsyncMock()

        with (
            mock.patch.object(
                discord_ops, "require_category", return_value=self.category
            ),
            mock.patch.object(
                discord_ops, "require_role_channel", return_value=self.role_channel
            ),
            mock.patch.object(
                discord_ops,
                "create_discussion_channel",
                new=mock.AsyncMock(return_value=self.discussion),
            ),
            mock.patch.object(
                discord_ops,
                "create_voice_channel",
                new=mock.AsyncMock(return_value=self.voice),
            ),
            mock.patch.object(discord_ops, "cleanup_resources", new=cleanup),
            mock.patch("bot.features.ctf_team.cog.send_interaction", new=send),
            mock.patch("bot.features.ctf_team.cog.log_audit", new=audit),
        ):
            await self.submit()

        cleanup.assert_not_awaited()
        active = self.db.find_active_campaign_by_name(
            ctf_name="Example",
        )
        self.assertIsNotNone(active)
        send.assert_awaited_once_with(
            self.interaction,
            "**Example** の募集を作成しました。\n"
            "⚠️ 作成者へのロール付与に失敗しました。"
            "募集メッセージに ✅ リアクションすると参加できます。",
        )
        audit.assert_awaited_once()

    async def test_failure_before_insert_cleans_up_created_resources(self) -> None:
        cleanup = mock.AsyncMock()
        send = mock.AsyncMock()
        create_discussion = mock.AsyncMock(
            side_effect=ServiceError("チャンネル作成に失敗しました。")
        )

        with (
            mock.patch.object(
                discord_ops, "require_category", return_value=self.category
            ),
            mock.patch.object(
                discord_ops, "require_role_channel", return_value=self.role_channel
            ),
            mock.patch.object(
                discord_ops,
                "create_discussion_channel",
                new=create_discussion,
            ),
            mock.patch.object(discord_ops, "cleanup_resources", new=cleanup),
            mock.patch("bot.features.ctf_team.cog.send_interaction", new=send),
        ):
            await self.submit()

        cleanup.assert_awaited_once_with(
            message=None,
            role=self.role,
            discussion=None,
            voice=None,
        )
        active = self.db.find_active_campaign_by_name(
            ctf_name="Example",
        )
        self.assertIsNone(active)
        send.assert_awaited_once_with(
            self.interaction,
            "チャンネル作成に失敗しました。",
        )
