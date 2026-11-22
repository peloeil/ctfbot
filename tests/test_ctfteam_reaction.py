from types import SimpleNamespace
from typing import Any
from unittest import mock

import discord

from tests.ctfteam_support import GUILD_ID, ROLE_CHANNEL_ID, CTFTeamTestCase, http_error

MEMBER_ID = 11


class ReactionTestCase(CTFTeamTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.guild = mock.Mock(spec=discord.Guild)
        self.discussion = mock.Mock(spec=discord.TextChannel)
        self.discussion.send = mock.AsyncMock()
        self.recruit_channel = mock.Mock(spec=discord.TextChannel)
        self.voice = mock.Mock(spec=discord.VoiceChannel)
        self.voice.delete = mock.AsyncMock()
        channels = {
            5: self.discussion,
            ROLE_CHANNEL_ID: self.recruit_channel,
            6: self.voice,
        }
        self.guild.get_channel.side_effect = channels.get
        self.role = mock.Mock(spec=discord.Role)
        self.role.members = []
        self.guild.get_role.return_value = self.role
        self.member = mock.Mock(spec=discord.Member)
        self.member.name = "joiner"
        self.member.mention = f"<@{MEMBER_ID}>"
        self.member.roles = []
        self.member.add_roles = mock.AsyncMock()
        self.guild.get_member.return_value = self.member
        self.bot.get_guild.return_value = self.guild

    @staticmethod
    def payload(**overrides: Any) -> Any:
        values: dict[str, Any] = {
            "emoji": "✅",
            "user_id": MEMBER_ID,
            "guild_id": GUILD_ID,
            "channel_id": ROLE_CHANNEL_ID,
            "message_id": 3,
        }
        return SimpleNamespace(**{**values, **overrides})

    async def react(self, payload: Any) -> None:
        await self.cog.on_raw_reaction_add(payload)


class ParticipationReactionTest(ReactionTestCase):
    async def test_check_reaction_grants_role_and_announces_join(self) -> None:
        self.create_active()

        await self.react(self.payload())

        self.member.add_roles.assert_awaited_once_with(self.role)
        self.discussion.send.assert_awaited_once()
        self.assertEqual(
            self.discussion.send.call_args.args[0],
            f"🙋 <@{MEMBER_ID}> が **Example** に参加しました。",
        )

    async def test_member_who_already_has_role_gets_no_second_grant_or_notice(
        self,
    ) -> None:
        self.create_active()
        self.member.roles = [self.role]

        await self.react(self.payload())

        self.member.add_roles.assert_not_awaited()
        self.discussion.send.assert_not_awaited()

    async def test_failed_role_grant_is_not_announced(self) -> None:
        self.create_active()
        self.member.add_roles.side_effect = http_error(discord.Forbidden, 403)

        with self.assertLogs("ctfbot", level="WARNING"):
            await self.react(self.payload())

        self.discussion.send.assert_not_awaited()

    async def test_deleted_role_is_ignored(self) -> None:
        self.create_active()
        self.guild.get_role.return_value = None

        await self.react(self.payload())

        self.member.add_roles.assert_not_awaited()

    async def test_unresolvable_member_is_ignored(self) -> None:
        self.create_active()
        self.guild.get_member.return_value = None
        self.guild.fetch_member = mock.AsyncMock(
            side_effect=http_error(discord.NotFound, 404)
        )

        await self.react(self.payload())

        self.member.add_roles.assert_not_awaited()
        self.discussion.send.assert_not_awaited()

    async def test_reactions_that_are_not_participation_are_ignored(self) -> None:
        self.create_active()
        ignored = {
            "other emoji": self.payload(emoji="👍"),
            "bot itself": self.payload(user_id=self.bot.user.id),
            "direct message": self.payload(guild_id=None),
            "other message": self.payload(message_id=999),
        }

        for label, payload in ignored.items():
            with self.subTest(label):
                await self.react(payload)

                self.member.add_roles.assert_not_awaited()

    async def test_reaction_on_closed_campaign_is_ignored(self) -> None:
        self.create_closed()

        await self.react(self.payload())

        self.member.add_roles.assert_not_awaited()


class ExpiredCampaignReactionTest(ReactionTestCase):
    async def test_reaction_on_expired_campaign_closes_it_without_granting_role(
        self,
    ) -> None:
        self.create_active(end_at_unix=200)
        message = mock.Mock(spec=discord.Message, content="Original")
        message.edit = mock.AsyncMock()
        self.recruit_channel.fetch_message = mock.AsyncMock(return_value=message)

        await self.react(self.payload())

        self.assertIsNotNone(self.db.find_closed_campaign_by_name(ctf_name="Example"))
        self.member.add_roles.assert_not_awaited()
        self.voice.delete.assert_awaited_once()
        self.assert_not_audited()
