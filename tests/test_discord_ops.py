import unittest
from types import SimpleNamespace
from typing import Any
from unittest import mock

import discord

from ctfbot.errors import ServiceError
from ctfbot.features.ctfteam import discord_ops
from ctfbot.features.ctfteam.models import CampaignDraft


class RequireCategoryTest(unittest.TestCase):
    def test_unconfigured_feature_raises(self) -> None:
        guild = mock.Mock(spec=discord.Guild)
        with self.assertRaisesRegex(ServiceError, "ctfteam 機能が設定されていません。"):
            discord_ops.require_category(guild, None)
        guild.get_channel.assert_not_called()

    def test_returns_category_channel(self) -> None:
        guild = mock.Mock(spec=discord.Guild)
        category = mock.Mock(spec=discord.CategoryChannel)
        guild.get_channel.return_value = category
        result = discord_ops.require_category(guild, 123)
        self.assertIs(result, category)

    def test_raises_when_not_found(self) -> None:
        guild = mock.Mock(spec=discord.Guild)
        guild.get_channel.return_value = None
        with self.assertRaises(ServiceError):
            discord_ops.require_category(guild, 123)

    def test_raises_when_wrong_type(self) -> None:
        guild = mock.Mock(spec=discord.Guild)
        guild.get_channel.return_value = mock.Mock(spec=discord.TextChannel)
        with self.assertRaises(ServiceError):
            discord_ops.require_category(guild, 123)


class RequireRoleChannelTest(unittest.TestCase):
    def test_returns_role_channel(self) -> None:
        guild = mock.Mock(spec=discord.Guild)
        role_channel = mock.Mock(spec=discord.TextChannel)
        guild.get_channel.return_value = role_channel

        result = discord_ops.require_role_channel(guild, 456)

        self.assertIs(result, role_channel)
        guild.get_channel.assert_called_once_with(456)

    def test_raises_when_not_found(self) -> None:
        guild = mock.Mock(spec=discord.Guild)
        guild.get_channel.return_value = None

        with self.assertRaisesRegex(ServiceError, "募集チャンネルが見つかりません。"):
            discord_ops.require_role_channel(guild, 456)

    def test_raises_when_channel_is_not_text_channel(self) -> None:
        guild = mock.Mock(spec=discord.Guild)
        guild.get_channel.return_value = mock.Mock(spec=discord.CategoryChannel)

        with self.assertRaisesRegex(ServiceError, "募集チャンネルが見つかりません。"):
            discord_ops.require_role_channel(guild, 456)


class DiscordOpsTest(unittest.TestCase):
    def test_normalize_channel_name_lowercases_and_replaces_spaces(self) -> None:
        self.assertEqual(
            discord_ops.normalize_channel_name("My CTF 2026"), "my-ctf-2026"
        )

    def test_normalize_channel_name_preserves_japanese(self) -> None:
        self.assertEqual(
            discord_ops.normalize_channel_name("ボードゲーム"), "ボードゲーム"
        )

    def test_normalize_channel_name_replaces_symbols_and_collapses_dashes(
        self,
    ) -> None:
        self.assertEqual(discord_ops.normalize_channel_name("a!!b--c"), "a-b-c")

    def test_normalize_channel_name_falls_back_for_symbols(self) -> None:
        self.assertEqual(discord_ops.normalize_channel_name("!!!"), "ctf")

    def test_normalize_channel_name_truncates_to_100_characters(self) -> None:
        self.assertEqual(discord_ops.normalize_channel_name("A" * 101), "a" * 100)

    def test_pick_unique_channel_name_returns_unused_base(self) -> None:
        category = mock.Mock(spec=discord.CategoryChannel)
        category.channels = [SimpleNamespace(name="other")]
        self.assertEqual(discord_ops.pick_unique_channel_name(category, "base"), "base")

    def test_pick_unique_channel_name_increments_suffix(self) -> None:
        category = mock.Mock(spec=discord.CategoryChannel)
        category.channels = [
            SimpleNamespace(name="base"),
            SimpleNamespace(name="base-2"),
        ]
        self.assertEqual(
            discord_ops.pick_unique_channel_name(category, "base"), "base-3"
        )

    def test_pick_unique_channel_name_limits_suffixed_name_length(self) -> None:
        base = "a" * 100
        category = mock.Mock(spec=discord.CategoryChannel)
        category.channels = [SimpleNamespace(name=base)]
        result = discord_ops.pick_unique_channel_name(category, base)
        self.assertEqual(len(result), 100)
        self.assertTrue(result.endswith("-2"))

    def test_build_recruitment_message_includes_end_timestamp(self) -> None:
        role = mock.Mock(spec=discord.Role)
        role.mention = "<@&4>"
        channel = mock.Mock(spec=discord.TextChannel)
        channel.mention = "<#5>"
        draft = CampaignDraft(ctf_name="Example", start_at_unix=100, end_at_unix=200)
        message = discord_ops.build_recruitment_message(draft, role, channel)
        self.assertIn("<t:200:f>", message)
        self.assertIn("<@&4>", message)
        self.assertIn("<#5>", message)

    def test_build_recruitment_message_labels_permanent_campaign(self) -> None:
        role = mock.Mock(spec=discord.Role)
        role.mention = "<@&4>"
        channel = mock.Mock(spec=discord.TextChannel)
        channel.mention = "<#5>"
        draft = CampaignDraft(ctf_name="Example", start_at_unix=100, end_at_unix=None)
        message = discord_ops.build_recruitment_message(draft, role, channel)
        self.assertIn("常設", message)


class MarkMessageClosedTest(unittest.IsolatedAsyncioTestCase):
    async def test_not_found_is_success(self) -> None:
        channel = mock.Mock(spec=discord.TextChannel)
        response = mock.Mock(status=404, reason="Not Found")
        channel.fetch_message.side_effect = discord.NotFound(response, "not found")
        self.assertTrue(await discord_ops.mark_message_closed(channel, 1))

    async def test_forbidden_is_failure(self) -> None:
        channel = mock.Mock(spec=discord.TextChannel)
        response = mock.Mock(status=403, reason="Forbidden")
        channel.fetch_message.side_effect = discord.Forbidden(response, "forbidden")
        with self.assertLogs("ctfbot", level="WARNING"):
            self.assertFalse(await discord_ops.mark_message_closed(channel, 1))

    async def test_already_closed_message_is_not_edited(self) -> None:
        channel = mock.Mock(spec=discord.TextChannel)
        message = mock.Mock(spec=discord.Message)
        message.content = f"{discord_ops.CLOSED_HEADER}\n\nOriginal"
        channel.fetch_message.return_value = message
        self.assertTrue(await discord_ops.mark_message_closed(channel, 1))
        message.edit.assert_not_awaited()


def make_role(members: list[Any]) -> Any:
    role = mock.Mock(spec=discord.Role)
    role.members = members
    return role


def make_members(count: int) -> list[Any]:
    return [SimpleNamespace(mention=f"<@{index:04d}>") for index in range(count)]


def make_channel() -> Any:
    channel = mock.Mock(spec=discord.TextChannel)
    channel.send = mock.AsyncMock()
    return channel


def sent_contents(channel: Any) -> list[str]:
    return [call.args[0] for call in channel.send.await_args_list]


class CloseSnapshotTest(unittest.IsolatedAsyncioTestCase):
    async def test_header_shows_member_count_and_members_follow(self) -> None:
        channel = make_channel()

        result = await discord_ops.send_close_snapshot(
            channel, "Example", make_role(make_members(2))
        )

        self.assertEqual(result, (2, True))
        self.assertEqual(
            sent_contents(channel),
            [
                "🔒 **Example** の募集が終了しました。\n参加メンバー (2人):",
                "<@0000> <@0001>",
            ],
        )

    async def test_no_members_sends_header_only(self) -> None:
        channel = make_channel()

        result = await discord_ops.send_close_snapshot(
            channel, "Example", make_role([])
        )

        self.assertEqual(result, (0, True))
        self.assertEqual(
            sent_contents(channel),
            ["🔒 **Example** の募集が終了しました。\n参加メンバー (0人):"],
        )

    async def test_many_members_are_split_within_message_limit_in_order(self) -> None:
        channel = make_channel()
        members = make_members(300)

        await discord_ops.send_close_snapshot(channel, "Example", make_role(members))

        chunks = sent_contents(channel)[1:]
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 1700 for chunk in chunks))
        self.assertEqual(
            [mention for chunk in chunks for mention in chunk.split()],
            [member.mention for member in members],
        )

    async def test_header_suppresses_mentions_and_member_chunks_ping_users_only(
        self,
    ) -> None:
        channel = make_channel()

        await discord_ops.send_close_snapshot(
            channel, "Example", make_role(make_members(1))
        )

        header, chunk = channel.send.await_args_list
        header_mentions = header.kwargs["allowed_mentions"]
        chunk_mentions = chunk.kwargs["allowed_mentions"]
        self.assertEqual(
            (header_mentions.everyone, header_mentions.users, header_mentions.roles),
            (False, False, False),
        )
        self.assertEqual(
            (chunk_mentions.everyone, chunk_mentions.users, chunk_mentions.roles),
            (False, True, False),
        )

    async def test_failed_send_is_reported_as_failure(self) -> None:
        channel = make_channel()
        channel.send.side_effect = discord.HTTPException(
            mock.Mock(status=500, reason="error"), "error"
        )

        with self.assertLogs("ctfbot", level="ERROR"):
            result = await discord_ops.send_close_snapshot(
                channel, "Example", make_role([])
            )

        self.assertEqual(result, (0, False))


class AnnouncementTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_announcement_names_campaign_then_mentions_members(
        self,
    ) -> None:
        channel = make_channel()

        result = await discord_ops.send_start_announcement(
            channel, "Example", make_role(make_members(1))
        )

        self.assertEqual(result, (1, True))
        self.assertEqual(
            sent_contents(channel), ["🚀 **Example** が開始しました!", "<@0000>"]
        )

    async def test_join_announcement_pings_only_the_joined_member(self) -> None:
        channel = make_channel()
        member = mock.Mock(spec=discord.Member, mention="<@11>")

        await discord_ops.send_join_announcement(channel, member, "Example")

        self.assertEqual(
            sent_contents(channel), ["🙋 <@11> が **Example** に参加しました。"]
        )
        mentions = channel.send.call_args.kwargs["allowed_mentions"]
        self.assertEqual(
            (mentions.everyone, mentions.users, mentions.roles),
            (False, [member], False),
        )


class ChannelCreationTest(unittest.IsolatedAsyncioTestCase):
    def make_guild(self) -> Any:
        guild = mock.Mock(spec=discord.Guild)
        guild.default_role = mock.Mock(spec=discord.Role)
        guild.create_text_channel = mock.AsyncMock()
        guild.create_voice_channel = mock.AsyncMock()
        return guild

    def make_category(self, existing: list[str]) -> Any:
        category = mock.Mock(spec=discord.CategoryChannel)
        category.channels = [SimpleNamespace(name=name) for name in existing]
        return category

    def assert_allows_exactly(
        self, overwrite: discord.PermissionOverwrite, names: set[str]
    ) -> None:
        allow, deny = overwrite.pair()
        self.assertEqual(allow, discord.Permissions(**dict.fromkeys(names, True)))
        self.assertEqual(deny, discord.Permissions.none())

    async def test_discussion_is_visible_only_to_role_creator_and_bot(self) -> None:
        guild = self.make_guild()
        role = mock.Mock(spec=discord.Role)
        creator = mock.Mock(spec=discord.Member)
        bot_member = mock.Mock(spec=discord.Member)

        await discord_ops.create_discussion_channel(
            guild, self.make_category([]), "My CTF", role, creator, bot_member
        )

        kwargs = guild.create_text_channel.call_args.kwargs
        overwrites = kwargs["overwrites"]
        participant = {"view_channel", "send_messages", "read_message_history"}
        self.assertEqual(kwargs["name"], "my-ctf")
        self.assertIs(overwrites[guild.default_role].view_channel, False)
        self.assert_allows_exactly(overwrites[role], participant)
        self.assert_allows_exactly(overwrites[creator], participant)
        self.assert_allows_exactly(
            overwrites[bot_member], participant | {"manage_channels"}
        )

    async def test_voice_is_visible_only_to_role_creator_and_bot(self) -> None:
        guild = self.make_guild()
        role = mock.Mock(spec=discord.Role)
        creator = mock.Mock(spec=discord.Member)
        bot_member = mock.Mock(spec=discord.Member)

        await discord_ops.create_voice_channel(
            guild, self.make_category([]), "My CTF", role, creator, bot_member
        )

        kwargs = guild.create_voice_channel.call_args.kwargs
        overwrites = kwargs["overwrites"]
        participant = {"view_channel", "connect", "speak", "stream"}
        self.assertEqual(kwargs["name"], "my-ctf-voice")
        self.assertIs(overwrites[guild.default_role].view_channel, False)
        for target in (role, creator, bot_member):
            with self.subTest(target=target):
                self.assert_allows_exactly(overwrites[target], participant)

    async def test_missing_creator_and_bot_get_no_overwrites(self) -> None:
        guild = self.make_guild()
        role = mock.Mock(spec=discord.Role)

        await discord_ops.create_discussion_channel(
            guild, self.make_category([]), "Example", role, None, None
        )

        overwrites = guild.create_text_channel.call_args.kwargs["overwrites"]
        self.assertEqual(set(overwrites), {guild.default_role, role})

    async def test_name_clashing_with_any_channel_in_category_gets_suffix(
        self,
    ) -> None:
        guild = self.make_guild()
        category = self.make_category(["example", "example-voice"])
        role = mock.Mock(spec=discord.Role)

        await discord_ops.create_discussion_channel(
            guild, category, "Example", role, None, None
        )
        await discord_ops.create_voice_channel(
            guild, category, "Example", role, None, None
        )

        self.assertEqual(
            guild.create_text_channel.call_args.kwargs["name"], "example-2"
        )
        self.assertEqual(
            guild.create_voice_channel.call_args.kwargs["name"], "example-voice-2"
        )


class CleanupResourcesTest(unittest.IsolatedAsyncioTestCase):
    async def test_resources_are_deleted_in_reverse_creation_order(self) -> None:
        order: list[str] = []
        resources: dict[str, Any] = {}
        for name, spec in (
            ("message", discord.Message),
            ("role", discord.Role),
            ("discussion", discord.TextChannel),
            ("voice", discord.VoiceChannel),
        ):
            resource = mock.Mock(spec=spec)
            resource.delete = mock.AsyncMock(
                side_effect=lambda name=name: order.append(name)
            )
            resources[name] = resource

        await discord_ops.cleanup_resources(**resources)

        self.assertEqual(order, ["message", "voice", "discussion", "role"])

    async def test_failed_deletion_does_not_stop_remaining_deletions(self) -> None:
        voice = mock.Mock(spec=discord.VoiceChannel)
        voice.delete = mock.AsyncMock(
            side_effect=discord.Forbidden(mock.Mock(status=403, reason="x"), "x")
        )
        role = mock.Mock(spec=discord.Role)
        role.delete = mock.AsyncMock()

        with self.assertLogs("ctfbot", level="WARNING"):
            await discord_ops.cleanup_resources(voice=voice, role=role)

        role.delete.assert_awaited_once()

    async def test_nothing_to_delete_is_a_no_op(self) -> None:
        await discord_ops.cleanup_resources()


class DeleteVoiceChannelTest(unittest.IsolatedAsyncioTestCase):
    def make_bot_and_guild(self) -> tuple[Any, Any]:
        bot = mock.Mock()
        bot.fetch_channel = mock.AsyncMock()
        return bot, mock.Mock(spec=discord.Guild)

    async def test_campaign_without_voice_channel_succeeds(self) -> None:
        bot, guild = self.make_bot_and_guild()

        self.assertTrue(await discord_ops.delete_voice_channel(bot, guild, None))

    async def test_cached_voice_channel_is_deleted(self) -> None:
        bot, guild = self.make_bot_and_guild()
        voice = mock.Mock(spec=discord.VoiceChannel)
        voice.delete = mock.AsyncMock()
        guild.get_channel.return_value = voice

        result = await discord_ops.delete_voice_channel(bot, guild, 6)

        self.assertTrue(result)
        voice.delete.assert_awaited_once()

    async def test_voice_channel_already_gone_counts_as_success(self) -> None:
        bot, guild = self.make_bot_and_guild()
        guild.get_channel.return_value = None
        bot.fetch_channel.side_effect = discord.NotFound(
            mock.Mock(status=404, reason="x"), "x"
        )

        self.assertTrue(await discord_ops.delete_voice_channel(bot, guild, 6))

    async def test_forbidden_deletion_is_failure(self) -> None:
        bot, guild = self.make_bot_and_guild()
        voice = mock.Mock(spec=discord.VoiceChannel)
        voice.delete = mock.AsyncMock(
            side_effect=discord.Forbidden(mock.Mock(status=403, reason="x"), "x")
        )
        guild.get_channel.return_value = voice

        with self.assertLogs("ctfbot", level="WARNING"):
            result = await discord_ops.delete_voice_channel(bot, guild, 6)

        self.assertFalse(result)
