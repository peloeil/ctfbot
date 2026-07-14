import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from bot.errors import ServiceError
from bot.features.ctf_team import discord_ops
from bot.features.ctf_team.models import CampaignDraft


class RequireCategoryTest(unittest.TestCase):
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
        category = mock.Mock(spec=discord.CategoryChannel)
        role_channel = mock.Mock(spec=discord.TextChannel)
        role_channel.name = discord_ops.ROLE_ANNOUNCE_CHANNEL_NAME
        category.text_channels = [role_channel]

        result = discord_ops.require_role_channel(category)

        self.assertIs(result, role_channel)

    def test_raises_when_not_found(self) -> None:
        category = mock.Mock(spec=discord.CategoryChannel)
        category.text_channels = []

        with self.assertRaises(ServiceError):
            discord_ops.require_role_channel(category)


class DiscordOpsTest(unittest.TestCase):
    def test_normalize_channel_name_lowercases_and_replaces_spaces(self) -> None:
        self.assertEqual(
            discord_ops.normalize_channel_name("My CTF 2026"), "my-ctf-2026"
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

    def test_chunk_mentions_returns_empty_list(self) -> None:
        self.assertEqual(discord_ops._chunk_mentions([]), [])

    def test_chunk_mentions_joins_small_input(self) -> None:
        mentions = ["<@1>", "<@2>", "<@3>"]
        self.assertEqual(discord_ops._chunk_mentions(mentions), ["<@1> <@2> <@3>"])

    def test_chunk_mentions_splits_long_input_without_reordering(self) -> None:
        mentions = [f"<@{index:04d}>" for index in range(300)]
        chunks = discord_ops._chunk_mentions(mentions)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(
            all(len(chunk) <= discord_ops.MENTION_CHUNK_SIZE for chunk in chunks)
        )
        self.assertEqual(
            [mention for chunk in chunks for mention in chunk.split()], mentions
        )

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
        self.assertFalse(await discord_ops.mark_message_closed(channel, 1))

    async def test_already_closed_message_is_not_edited(self) -> None:
        channel = mock.Mock(spec=discord.TextChannel)
        message = mock.Mock(spec=discord.Message)
        message.content = f"{discord_ops.CLOSED_HEADER}\n\nOriginal"
        channel.fetch_message.return_value = message
        self.assertTrue(await discord_ops.mark_message_closed(channel, 1))
        message.edit.assert_not_awaited()
