import asyncio
import datetime
import os
import tempfile
import unittest
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import discord

from ctfbot.db import Database
from ctfbot.features.ctfteam.cog import CTFTeamCampaigns
from ctfbot.features.ctfteam.models import ActiveCampaign, ClosedCampaign
from ctfbot.runtime import BotRuntime

GUILD_ID = 1
CREATOR_ID = 7
CATEGORY_ID = 8
ROLE_CHANNEL_ID = 9
ARCHIVE_CATEGORY_ID = 10
AUDIT_CHANNEL_ID = 99


def http_error(error: type[discord.HTTPException], status: int) -> Exception:
    return error(mock.Mock(status=status, reason="error"), "error")


async def _never() -> None:
    await asyncio.Event().wait()


class CTFTeamTestCase(unittest.IsolatedAsyncioTestCase):
    """Builds a real cog on a temporary DB; the Discord side is mocked."""

    async def asyncSetUp(self) -> None:
        fd, path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(path)
        self.addCleanup(self._remove_db, path)
        self.db = Database(path)

        self.audit_channel = mock.Mock(spec=discord.TextChannel)
        self.audit_channel.send = mock.AsyncMock()
        self.bot = mock.Mock()
        self.bot.user = SimpleNamespace(id=100)
        self.bot.get_channel.return_value = self.audit_channel
        # Keeps the background loops parked so tests drive them explicitly.
        self.bot.wait_until_ready = _never
        settings = SimpleNamespace(
            tzinfo=datetime.UTC,
            guild_id=GUILD_ID,
            ctfteam_category_id=CATEGORY_ID,
            ctfteam_role_channel_id=ROLE_CHANNEL_ID,
            ctfteam_archive_category_id=ARCHIVE_CATEGORY_ID,
            bot_channel_id=AUDIT_CHANNEL_ID,
        )
        self.settings: Any = settings
        self.bot.runtime = BotRuntime(settings=cast(Any, settings), db=self.db)
        self.cog = CTFTeamCampaigns(self.bot)
        self.addAsyncCleanup(self.cog.cog_unload)

    @staticmethod
    def _remove_db(path: str) -> None:
        for suffix in ("", "-wal", "-shm"):
            with suppress(FileNotFoundError):
                os.unlink(path + suffix)

    def create_active(
        self,
        name: str = "Example",
        *,
        created_by: int = CREATOR_ID,
        start_at_unix: int = 100,
        end_at_unix: int | None = None,
        message_id: int = 3,
    ) -> ActiveCampaign:
        return self.db.create_campaign(
            channel_id=ROLE_CHANNEL_ID,
            message_id=message_id,
            role_id=4,
            discussion_channel_id=5,
            voice_channel_id=6,
            ctf_name=name,
            start_at_unix=start_at_unix,
            end_at_unix=end_at_unix,
            created_by=created_by,
            created_at_unix=90,
            max_active_per_creator=100,
        )

    def create_closed(
        self,
        name: str = "Example",
        *,
        created_by: int = CREATOR_ID,
        archive_at_unix: int = 300,
        message_id: int = 3,
    ) -> ClosedCampaign:
        active = self.create_active(
            name, created_by=created_by, end_at_unix=200, message_id=message_id
        )
        self.db.close_campaign(active.id, 201, archive_at_unix)
        closed = self.db.find_closed_campaign_by_name(ctf_name=name)
        assert closed is not None
        return closed

    @staticmethod
    def make_interaction(
        *,
        user_id: int = CREATOR_ID,
        manage_guild: bool = False,
        guild: discord.Guild | None = None,
    ) -> Any:
        """Interaction whose replies are recorded on response/followup mocks."""
        interaction = mock.Mock(spec=discord.Interaction)
        interaction.user = SimpleNamespace(
            id=user_id,
            name="user",
            guild_permissions=discord.Permissions(manage_guild=manage_guild),
        )
        interaction.guild = guild
        interaction.channel = None
        interaction.channel_id = 50
        deferred = False

        async def defer(**_: object) -> None:
            nonlocal deferred
            deferred = True

        interaction.response = mock.Mock()
        interaction.response.defer = mock.AsyncMock(side_effect=defer)
        interaction.response.is_done.side_effect = lambda: deferred
        interaction.response.send_message = mock.AsyncMock()
        interaction.response.send_modal = mock.AsyncMock()
        interaction.followup = mock.Mock()
        interaction.followup.send = mock.AsyncMock()
        return interaction

    def assert_replied_ephemerally(self, interaction: Any, content: str) -> None:
        """Asserts exactly one reply, sent only to the invoker."""
        sent = [
            *interaction.response.send_message.await_args_list,
            *interaction.followup.send.await_args_list,
        ]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].args, (content,))
        self.assertIs(sent[0].kwargs["ephemeral"], True)

    def assert_audited(self, command_name: str) -> None:
        self.audit_channel.send.assert_awaited_once()
        self.assertIn(f"`/{command_name}`", self.audit_channel.send.call_args.args[0])

    def assert_not_audited(self) -> None:
        self.audit_channel.send.assert_not_awaited()
