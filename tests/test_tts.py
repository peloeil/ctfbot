import asyncio
import tempfile
import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import discord
from discord import app_commands
from discord.ext import commands

from ctfbot.db import Database
from ctfbot.errors import ExternalAPIError, RepositoryError
from ctfbot.features.tts import cog as tts_cog
from ctfbot.features.tts.cog import (
    CATALOG_RETRY_SECONDS,
    CATALOG_TTL_SECONDS,
    MAX_QUEUE_SIZE,
    TTS,
)
from ctfbot.features.tts.service import Voice
from ctfbot.runtime import BotRuntime

GUILD_ID = 99
BOT_ID = 42
CHANNEL_A = 10
CHANNEL_B = 11
ALICE = 1
BOB = 2
ADMIN = 3
CAROL = 4
POOL = (3, 2, 8)
VOICES = tuple(Voice(i, f"キャラ{i}", "ノーマル") for i in (1, 2, 3, 8, 11))


class FakeVoiceClient:
    def __init__(self) -> None:
        self.playing = False
        self.after: Callable[[Exception | None], None] | None = None
        self.play_calls = 0
        self.play_error: Exception | None = None
        self.disconnect = mock.AsyncMock()

    def is_playing(self) -> bool:
        return self.playing

    def play(self, source: object, after: Callable[[Exception | None], None]) -> None:
        if self.play_error is not None:
            raise self.play_error
        self.play_calls += 1
        self.playing = True
        self.after = after

    def stop(self) -> None:
        self.finish()

    def finish(self) -> None:
        self.playing = False
        if self.after is not None:
            after, self.after = self.after, None
            after(None)


def make_channel(channel_id: int, voice_client: FakeVoiceClient) -> mock.Mock:
    channel = mock.Mock(spec=discord.VoiceChannel)
    channel.id = channel_id
    channel.mention = f"<#{channel_id}>"
    channel.connect = mock.AsyncMock(return_value=voice_client)
    channel.permissions_for.return_value = SimpleNamespace(
        view_channel=True, connect=True, speak=True
    )
    return channel


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


class TTSTestCase(unittest.IsolatedAsyncioTestCase):
    grace_seconds = 0.05

    async def asyncSetUp(self) -> None:
        self.voice_client = FakeVoiceClient()
        self.channels = {
            CHANNEL_A: make_channel(CHANNEL_A, self.voice_client),
            CHANNEL_B: make_channel(CHANNEL_B, self.voice_client),
        }
        self.voice_of: dict[int, mock.Mock | None] = {}
        self.guild = mock.Mock()
        self.guild.id = GUILD_ID
        self.guild.voice_client = None
        self.names: dict[int, str] = {}
        self.guild.get_member.side_effect = lambda user_id: (
            SimpleNamespace(
                display_name=self.names.get(user_id, f"user{user_id}"),
                voice=SimpleNamespace(channel=self.voice_of[user_id]),
            )
            if user_id in self.voice_of
            else None
        )
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database(str(Path(tmp.name) / "test.db"))
        self.bot = mock.Mock()
        self.bot.user.id = BOT_ID
        self.bot.intents.message_content = True
        self.bot.runtime = BotRuntime(
            settings=cast(
                Any,
                SimpleNamespace(
                    guild_id=GUILD_ID,
                    tts_max_chars=200,
                    tts_voicevox_url="http://127.0.0.1:50021",
                    tts_speaker_ids=POOL,
                ),
            ),
            db=self.db,
        )
        self.client = mock.Mock()
        self.client.synthesize.return_value = b"RIFFdata"
        self.client.fetch_voices.return_value = VOICES
        self.cog = TTS(
            cast(Any, self.bot),
            self.client,
            grace_seconds=self.grace_seconds,
            playback_ready=True,
        )
        patcher = mock.patch.object(tts_cog.discord, "FFmpegPCMAudio")
        self.ffmpeg = patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncTearDown(self) -> None:
        await self.cog.cog_unload()

    def interaction(
        self, user_id: int, channel_id: int | None = CHANNEL_A, manage: bool = False
    ) -> mock.Mock:
        channel = self.channels[channel_id] if channel_id is not None else None
        self.voice_of[user_id] = channel
        interaction = mock.Mock()
        interaction.guild = self.guild
        interaction.user.id = user_id
        interaction.user.voice = SimpleNamespace(channel=channel) if channel else None
        interaction.user.guild_permissions.manage_guild = manage
        interaction.response.is_done.return_value = False
        interaction.response.defer = mock.AsyncMock(
            side_effect=lambda **_: interaction.response.is_done.configure_mock(
                return_value=True
            )
        )
        interaction.response.send_message = mock.AsyncMock()
        interaction.followup.send = mock.AsyncMock()
        return interaction

    def reply(self, interaction: mock.Mock) -> str:
        send = (
            interaction.followup.send
            if interaction.response.is_done()
            else interaction.response.send_message
        )
        return send.await_args.args[0]

    async def run_command(self, command: Any, interaction: mock.Mock) -> str:
        await command.callback(self.cog, interaction)
        return self.reply(interaction)

    async def join(self, user_id: int, channel_id: int = CHANNEL_A) -> str:
        return await self.run_command(
            self.cog.join, self.interaction(user_id, channel_id)
        )

    def message(
        self,
        user_id: int,
        content: str = "こんにちは",
        *,
        channel_id: int = CHANNEL_A,
        message_id: int = 1000,
    ) -> mock.Mock:
        message = mock.Mock()
        message.id = message_id
        message.guild.id = GUILD_ID
        message.channel.id = channel_id
        message.author.id = user_id
        message.author.bot = False
        message.author.display_name = f"user{user_id}"
        voice_channel = self.voice_of.get(user_id)
        message.author.voice = (
            SimpleNamespace(channel=voice_channel) if voice_channel else None
        )
        message.webhook_id = None
        message.type = discord.MessageType.default
        message.content = content
        return message

    def queued(self) -> int:
        assert self.cog.session is not None
        return self.cog.session.queue.qsize()

    def voice_state(self, channel_id: int | None) -> mock.Mock:
        state = mock.Mock()
        state.channel = self.channels[channel_id] if channel_id is not None else None
        return state

    def member(self, user_id: int) -> mock.Mock:
        member = mock.Mock()
        member.id = user_id
        member.guild.id = GUILD_ID
        return member


class JoinTest(TTSTestCase):
    async def test_requires_a_voice_channel(self) -> None:
        reply = await self.run_command(self.cog.join, self.interaction(ALICE, None))
        self.assertIn("ボイスチャンネルに参加", reply)
        stage = mock.Mock(spec=discord.StageChannel)
        interaction = self.interaction(BOB)
        interaction.user.voice = SimpleNamespace(channel=stage)
        reply = await self.run_command(self.cog.join, interaction)
        self.assertIn("ボイスチャンネルに参加", reply)
        self.assertIsNone(self.cog.session)

    async def test_missing_channel_permissions_are_rejected(self) -> None:
        for missing in ("view_channel", "connect", "speak"):
            with self.subTest(missing=missing):
                permissions = {"view_channel": True, "connect": True, "speak": True}
                permissions[missing] = False
                self.channels[CHANNEL_A].permissions_for.return_value = SimpleNamespace(
                    **permissions
                )
                reply = await self.join(ALICE)
                self.assertIn("権限がありません", reply)
                self.channels[CHANNEL_A].connect.assert_not_awaited()

    async def test_playback_not_ready_is_reported(self) -> None:
        self.cog.playback_ready = False
        self.assertEqual(await self.join(ALICE), "音声再生の準備ができていません。")
        self.channels[CHANNEL_A].connect.assert_not_awaited()

    async def test_join_defers_connects_deafened_and_opts_in(self) -> None:
        interaction = self.interaction(ALICE)
        await self.run_command(self.cog.join, interaction)
        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        self.channels[CHANNEL_A].connect.assert_awaited_once()
        self.assertTrue(self.channels[CHANNEL_A].connect.await_args.kwargs["self_deaf"])
        self.assertIn("開始しました", self.reply(interaction))
        assert self.cog.session is not None
        self.assertEqual(self.cog.session.channel_id, CHANNEL_A)
        self.assertEqual(set(self.cog.session.opted_in), {ALICE})

    async def test_other_channel_is_rejected_while_active(self) -> None:
        await self.join(ALICE)
        reply = await self.join(BOB, CHANNEL_B)
        self.assertEqual(reply, "既に別の VC で読み上げ中です。")
        self.channels[CHANNEL_B].connect.assert_not_awaited()
        assert self.cog.session is not None
        self.assertEqual(set(self.cog.session.opted_in), {ALICE})

    async def test_same_channel_adds_user_without_reconnecting(self) -> None:
        await self.join(ALICE)
        await self.join(BOB)
        self.channels[CHANNEL_A].connect.assert_awaited_once()
        assert self.cog.session is not None
        self.assertEqual(set(self.cog.session.opted_in), {ALICE, BOB})

    async def test_simultaneous_joins_from_different_channels_connect_once(
        self,
    ) -> None:
        async def slow_connect(**_: object) -> FakeVoiceClient:
            await asyncio.sleep(0.02)
            return self.voice_client

        self.channels[CHANNEL_A].connect.side_effect = slow_connect
        self.channels[CHANNEL_B].connect.side_effect = slow_connect
        replies = await asyncio.gather(
            self.join(ALICE, CHANNEL_A), self.join(BOB, CHANNEL_B)
        )
        connects = (
            self.channels[CHANNEL_A].connect.await_count
            + self.channels[CHANNEL_B].connect.await_count
        )
        self.assertEqual(connects, 1)
        self.assertEqual(
            sorted(reply.startswith("✅") for reply in replies), [False, True]
        )

    async def test_connect_failure_cleans_up_leftover_voice_client(self) -> None:
        for error in (
            TimeoutError(),
            discord.ClientException("Already connected"),
            discord.opus.OpusNotLoaded(),
            RuntimeError("davey library needed"),
        ):
            with self.subTest(error=type(error).__name__):
                leftover = FakeVoiceClient()
                self.guild.voice_client = leftover
                self.channels[CHANNEL_A].connect.side_effect = error
                reply = await self.join(ALICE)
                self.assertEqual(reply, "ボイスチャンネルに接続できませんでした。")
                leftover.disconnect.assert_awaited_once_with(force=True)
                self.assertIsNone(self.cog.session)

    async def test_user_who_left_during_connect_is_not_opted_in(self) -> None:
        async def connect_then_leave(**_: object) -> FakeVoiceClient:
            self.voice_of[ALICE] = None
            return self.voice_client

        self.channels[CHANNEL_A].connect.side_effect = connect_then_leave
        reply = await self.join(ALICE)
        self.assertIn("ボイスチャンネルに参加", reply)
        await wait_until(lambda: self.cog.session is None)
        self.voice_client.disconnect.assert_awaited_once_with(force=True)


class LeaveTest(TTSTestCase):
    async def test_leave_without_session(self) -> None:
        reply = await self.run_command(self.cog.leave, self.interaction(ALICE))
        self.assertEqual(reply, "読み上げは開始されていません。")

    async def test_leave_keeps_connection_while_others_remain(self) -> None:
        await self.join(ALICE)
        await self.join(BOB)
        reply = await self.run_command(self.cog.leave, self.interaction(ALICE))
        self.assertIn("外れました", reply)
        assert self.cog.session is not None
        self.assertEqual(set(self.cog.session.opted_in), {BOB})
        self.voice_client.disconnect.assert_not_awaited()

    async def test_last_user_leaving_disconnects(self) -> None:
        await self.join(ALICE)
        await self.run_command(self.cog.leave, self.interaction(ALICE))
        self.assertIsNone(self.cog.session)
        self.voice_client.disconnect.assert_awaited_once_with(force=True)

    async def test_non_member_cannot_leave_but_manager_can_end_everything(
        self,
    ) -> None:
        await self.join(ALICE)
        await self.join(BOB)
        reply = await self.run_command(self.cog.leave, self.interaction(ADMIN))
        self.assertIn("対象ではありません", reply)
        self.assertIsNotNone(self.cog.session)
        await self.run_command(self.cog.leave, self.interaction(ADMIN, manage=True))
        self.assertIsNone(self.cog.session)
        self.voice_client.disconnect.assert_awaited_once_with(force=True)


class MessageTest(TTSTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        # Keep the worker idle so queued items stay observable
        self.client.synthesize.side_effect = self.block_synthesis
        self.release = threading.Event()
        await self.join(ALICE)
        await self.join(BOB)

    def block_synthesis(self, text: str, speaker_id: int) -> bytes:
        self.release.wait(2)
        return b"RIFFdata"

    async def asyncTearDown(self) -> None:
        self.release.set()
        await super().asyncTearDown()

    async def feed(self, message: mock.Mock) -> int:
        before = self.queued()
        await self.cog.on_message(message)
        return self.queued() - before

    async def test_opted_in_member_in_the_voice_channel_is_queued(self) -> None:
        await self.cog.on_message(self.message(ALICE, message_id=1))
        await wait_until(lambda: self.client.synthesize.call_count == 1)
        self.assertEqual(self.client.synthesize.call_args.args[0], "こんにちは")
        self.assertEqual(await self.feed(self.message(BOB, message_id=2)), 1)

    async def test_ignored_messages(self) -> None:
        self.voice_of[ADMIN] = self.channels[CHANNEL_A]
        variants: dict[str, Callable[[], mock.Mock]] = {
            "other channel": lambda: self.message(ALICE, channel_id=999),
            "not opted in": lambda: self.message(ADMIN),
            "bot": lambda: self.bot_message(),
            "webhook": lambda: self.webhook_message(),
            "system": lambda: self.system_message(),
            "left the voice channel": lambda: self.left_message(),
            "empty": lambda: self.message(ALICE, content=""),
            "url only": lambda: self.message(ALICE, content="https://example.com"),
            "spoiler only": lambda: self.message(ALICE, content="||secret||"),
            "bot mention": lambda: self.message(ALICE, content=f"<@{BOT_ID}> hi"),
            "other guild": lambda: self.other_guild_message(),
        }
        for name, build in variants.items():
            with self.subTest(name=name):
                self.assertEqual(await self.feed(build()), 0)
        self.assertEqual(self.client.synthesize.call_count, 0)

    def bot_message(self) -> mock.Mock:
        message = self.message(ALICE)
        message.author.bot = True
        return message

    def webhook_message(self) -> mock.Mock:
        message = self.message(ALICE)
        message.webhook_id = 5
        return message

    def system_message(self) -> mock.Mock:
        message = self.message(ALICE)
        message.type = discord.MessageType.pins_add
        return message

    def left_message(self) -> mock.Mock:
        message = self.message(ALICE)
        message.author.voice = SimpleNamespace(channel=self.channels[CHANNEL_B])
        return message

    def other_guild_message(self) -> mock.Mock:
        message = self.message(ALICE)
        message.guild.id = 1
        return message

    async def test_reply_ping_without_bot_mention_is_read(self) -> None:
        message = self.message(ALICE, content="返信です")
        message.type = discord.MessageType.reply
        message.mentions = [self.bot.user]
        await self.cog.on_message(message)
        await wait_until(lambda: self.client.synthesize.call_count == 1)

    async def test_full_queue_drops_new_messages(self) -> None:
        await self.cog.on_message(self.message(ALICE, message_id=0))
        await wait_until(lambda: self.client.synthesize.call_count == 1)
        for index in range(MAX_QUEUE_SIZE):
            self.assertEqual(await self.feed(self.message(ALICE, message_id=index)), 1)
        with self.assertLogs("ctfbot", "WARNING"):
            self.assertEqual(await self.feed(self.message(ALICE, message_id=99)), 0)
        self.assertEqual(self.queued(), MAX_QUEUE_SIZE)


class PlaybackTest(TTSTestCase):
    async def test_item_is_played_from_memory_pipe(self) -> None:
        await self.join(ALICE)
        await self.cog.on_message(self.message(ALICE))
        await wait_until(lambda: self.voice_client.play_calls == 1)
        source_args = self.ffmpeg.call_args
        self.assertTrue(source_args.kwargs["pipe"])
        self.assertEqual(source_args.args[0].read(), b"RIFFdata")
        self.voice_client.finish()

    async def test_next_item_waits_for_playback_to_finish(self) -> None:
        await self.join(ALICE)
        await self.cog.on_message(self.message(ALICE, message_id=1))
        await self.cog.on_message(self.message(ALICE, message_id=2))
        await wait_until(lambda: self.voice_client.play_calls == 1)
        await asyncio.sleep(0.05)
        self.assertEqual(self.voice_client.play_calls, 1)
        self.voice_client.finish()
        await wait_until(lambda: self.voice_client.play_calls == 2)
        self.voice_client.finish()

    async def test_synthesis_failure_skips_only_that_item(self) -> None:
        self.client.synthesize.side_effect = [ExternalAPIError("down"), b"RIFFdata"]
        await self.join(ALICE)
        await self.cog.on_message(self.message(ALICE, message_id=1))
        await self.cog.on_message(self.message(ALICE, message_id=2))
        await wait_until(lambda: self.voice_client.play_calls == 1)
        self.voice_client.finish()

    async def test_after_called_twice_is_harmless(self) -> None:
        await self.join(ALICE)
        await self.cog.on_message(self.message(ALICE))
        await wait_until(lambda: self.voice_client.play_calls == 1)
        after = self.voice_client.after
        assert after is not None
        after(None)
        after(None)
        await asyncio.sleep(0.02)

    async def test_play_client_exception_moves_to_next_item(self) -> None:
        await self.join(ALICE)
        self.voice_client.play_error = discord.ClientException("reconnecting")
        await self.cog.on_message(self.message(ALICE, message_id=1))
        await wait_until(lambda: self.client.synthesize.call_count == 1)
        await asyncio.sleep(0.02)
        self.voice_client.play_error = None
        await self.cog.on_message(self.message(ALICE, message_id=2))
        await wait_until(lambda: self.voice_client.play_calls == 1)
        self.voice_client.finish()

    async def test_opus_not_loaded_ends_the_session(self) -> None:
        await self.join(ALICE)
        self.voice_client.play_error = discord.opus.OpusNotLoaded()
        await self.cog.on_message(self.message(ALICE))
        await wait_until(lambda: self.cog.session is None)
        self.voice_client.disconnect.assert_awaited_once_with(force=True)

    async def test_disconnect_during_synthesis_discards_the_old_item(self) -> None:
        release = threading.Event()
        started = threading.Event()

        def slow(text: str, speaker_id: int) -> bytes:
            started.set()
            release.wait(2)
            return b"RIFFdata"

        self.client.synthesize.side_effect = slow
        await self.join(ALICE)
        await self.cog.on_message(self.message(ALICE))
        await wait_until(started.is_set)
        await self.run_command(self.cog.leave, self.interaction(ALICE))
        self.assertIsNone(self.cog.session)

        new_client = FakeVoiceClient()
        self.channels[CHANNEL_A].connect.return_value = new_client
        await self.join(ALICE)
        release.set()
        await asyncio.sleep(0.1)
        self.assertEqual(self.voice_client.play_calls, 0)
        self.assertEqual(new_client.play_calls, 0)


class ControlTest(TTSTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.release = threading.Event()
        self.client.synthesize.side_effect = lambda text, speaker_id: (
            self.release.wait(2) and b"RIFFdata"
        )

    async def asyncTearDown(self) -> None:
        self.release.set()
        await super().asyncTearDown()

    async def test_skip_and_stop_require_a_session_and_permission(self) -> None:
        for command in (self.cog.skip, self.cog.stop):
            reply = await self.run_command(command, self.interaction(ALICE))
            self.assertEqual(reply, "読み上げは開始されていません。")
        await self.join(ALICE)
        for command in (self.cog.skip, self.cog.stop):
            reply = await self.run_command(command, self.interaction(BOB))
            self.assertIn("対象の人か、サーバー管理権限", reply)

    async def test_skip_stops_current_playback(self) -> None:
        self.client.synthesize.side_effect = None
        self.client.synthesize.return_value = b"RIFFdata"
        await self.join(ALICE)
        reply = await self.run_command(self.cog.skip, self.interaction(ALICE))
        self.assertEqual(reply, "再生中の読み上げはありません。")
        await self.cog.on_message(self.message(ALICE))
        await wait_until(lambda: self.voice_client.play_calls == 1)
        reply = await self.run_command(
            self.cog.skip, self.interaction(ADMIN, manage=True)
        )
        self.assertIn("スキップ", reply)
        self.assertFalse(self.voice_client.playing)

    async def test_stop_clears_queue_keeps_connection(self) -> None:
        await self.join(ALICE)
        for index in range(3):
            await self.cog.on_message(self.message(ALICE, message_id=index))
        await wait_until(lambda: self.client.synthesize.call_count == 1)
        self.assertEqual(self.queued(), 2)
        reply = await self.run_command(self.cog.stop, self.interaction(ALICE))
        self.assertIn("停止", reply)
        self.assertEqual(self.queued(), 0)
        self.voice_client.disconnect.assert_not_awaited()
        self.assertIsNotNone(self.cog.session)
        self.release.set()
        await asyncio.sleep(0.05)
        self.assertEqual(self.voice_client.play_calls, 0)


class LifecycleTest(TTSTestCase):
    async def test_leaving_the_channel_removes_opt_in_and_leaves_after_grace(
        self,
    ) -> None:
        await self.join(ALICE)
        await self.join(BOB)
        self.voice_of[ALICE] = self.channels[CHANNEL_B]
        await self.cog.on_voice_state_update(
            self.member(ALICE), self.voice_state(CHANNEL_A), self.voice_state(CHANNEL_B)
        )
        assert self.cog.session is not None
        self.assertEqual(set(self.cog.session.opted_in), {BOB})
        self.voice_client.disconnect.assert_not_awaited()

        # Re-entering does not restore the opt-in
        self.voice_of[ALICE] = self.channels[CHANNEL_A]
        await self.cog.on_voice_state_update(
            self.member(ALICE), self.voice_state(CHANNEL_B), self.voice_state(CHANNEL_A)
        )
        self.assertEqual(set(self.cog.session.opted_in), {BOB})

        await self.cog.on_voice_state_update(
            self.member(BOB), self.voice_state(CHANNEL_A), self.voice_state(None)
        )
        self.voice_client.disconnect.assert_not_awaited()
        await wait_until(lambda: self.cog.session is None)
        self.voice_client.disconnect.assert_awaited_once_with(force=True)

    async def test_join_during_grace_cancels_the_pending_leave(self) -> None:
        await self.join(ALICE)
        await self.cog.on_voice_state_update(
            self.member(ALICE), self.voice_state(CHANNEL_A), self.voice_state(None)
        )
        self.voice_of[BOB] = self.channels[CHANNEL_A]
        await self.join(BOB)
        await asyncio.sleep(self.grace_seconds * 3)
        self.assertIsNotNone(self.cog.session)
        self.voice_client.disconnect.assert_not_awaited()

    async def test_grace_leave_is_skipped_when_a_new_user_opted_in(self) -> None:
        await self.join(ALICE)
        await self.cog.on_voice_state_update(
            self.member(ALICE), self.voice_state(CHANNEL_A), self.voice_state(None)
        )
        assert self.cog.session is not None
        self.cog.session.voices[BOB] = 8
        await asyncio.sleep(self.grace_seconds * 3)
        self.assertIsNotNone(self.cog.session)

    async def test_bot_moved_to_another_channel_discards_state(self) -> None:
        await self.join(ALICE)
        await self.cog.on_voice_state_update(
            self.member(BOT_ID),
            self.voice_state(CHANNEL_A),
            self.voice_state(CHANNEL_B),
        )
        self.assertIsNone(self.cog.session)
        self.voice_client.disconnect.assert_awaited_once_with(force=True)

    async def test_external_disconnect_discards_state_without_reconnecting(
        self,
    ) -> None:
        await self.join(ALICE)
        await self.cog.on_voice_state_update(
            self.member(BOT_ID), self.voice_state(CHANNEL_A), self.voice_state(None)
        )
        self.assertIsNone(self.cog.session)
        self.channels[CHANNEL_A].connect.assert_awaited_once()

    async def test_bot_state_change_in_the_same_channel_is_ignored(self) -> None:
        await self.join(ALICE)
        await self.cog.on_voice_state_update(
            self.member(BOT_ID),
            self.voice_state(CHANNEL_A),
            self.voice_state(CHANNEL_A),
        )
        self.assertIsNotNone(self.cog.session)

    async def test_unload_disconnects(self) -> None:
        await self.join(ALICE)
        await self.cog.cog_unload()
        self.assertIsNone(self.cog.session)
        self.voice_client.disconnect.assert_awaited_once_with(force=True)


class VoiceTestCase(TTSTestCase):
    async def vset(
        self, user_id: int, query: str, channel_id: int | None = CHANNEL_A
    ) -> str:
        interaction = self.interaction(user_id, channel_id)
        await cast(Any, self.cog.voice_set).callback(self.cog, interaction, query)
        return self.reply(interaction)

    async def vshow(self, user_id: int) -> str:
        interaction = self.interaction(user_id, CHANNEL_A)
        return await self.run_command(self.cog.voice_show, interaction)

    async def vreset(self, user_id: int) -> str:
        interaction = self.interaction(user_id, CHANNEL_A)
        return await self.run_command(self.cog.voice_reset, interaction)

    def session_voice(self, user_id: int) -> int:
        assert self.cog.session is not None
        return self.cog.session.voices[user_id]

    def saved(self, user_id: int) -> int | None:
        return self.db.find_tts_voice(user_id)

    def save(self, user_id: int, speaker_id: int) -> None:
        self.db.upsert_tts_voice(user_id, speaker_id, 0)


class MembersTest(VoiceTestCase):
    async def members(self, user_id: int = ALICE, channel_id: int | None = CHANNEL_A):
        interaction = self.interaction(user_id, channel_id)
        reply = await self.run_command(self.cog.members, interaction)
        return interaction, reply

    def seed(self, count: int) -> None:
        assert self.cog.session is not None
        for user_id in range(100, 100 + count):
            self.voice_of[user_id] = self.channels[CHANNEL_A]
            self.cog.session.voices[user_id] = 3

    async def test_without_session(self) -> None:
        _, reply = await self.members()
        self.assertEqual(reply, "読み上げは開始されていません。")

    async def test_no_participants_during_grace(self) -> None:
        self.cog.grace_seconds = 10
        await self.join(ALICE)
        assert self.cog.session is not None
        self.cog.session.voices.clear()
        _, reply = await self.members()
        self.assertIn("参加者はいません", reply)
        self.assertIn(f"<#{CHANNEL_A}>", reply)

    async def test_lists_in_join_order_and_marks_the_caller(self) -> None:
        for user in (ALICE, BOB, CAROL):
            await self.join(user)
        _, reply = await self.members(BOB)
        lines = reply.split("\n")
        self.assertEqual(lines[0], f"🔊 <#{CHANNEL_A}> の読み上げ参加者（3 人）")
        expected = [
            f"- user{user}{'（あなた）' if user == BOB else ''}: "
            f"キャラ{self.session_voice(user)}（ノーマル）"
            for user in (ALICE, BOB, CAROL)
        ]
        self.assertEqual(lines[1:], expected)

    async def test_rejoin_moves_to_the_end_and_voice_change_keeps_order(self) -> None:
        for user in (ALICE, BOB, CAROL):
            await self.join(user)
        await self.run_command(self.cog.leave, self.interaction(BOB))
        await self.join(BOB)
        await self.vset(ALICE, "11")
        _, reply = await self.members()
        names = [line.split(":")[0] for line in reply.split("\n")[1:]]
        self.assertEqual(names, ["- user1（あなた）", f"- user{CAROL}", f"- user{BOB}"])
        self.assertIn("- user1（あなた）: キャラ11（ノーマル）", reply)

    async def test_caller_need_not_be_in_vc_or_opted_in(self) -> None:
        await self.join(ALICE)
        _, reply = await self.members(ADMIN, None)
        self.assertIn("（1 人）", reply)
        self.assertNotIn("あなた", reply)

    async def test_unknown_member(self) -> None:
        await self.join(ALICE)
        await self.join(BOB)
        del self.voice_of[BOB]
        _, reply = await self.members()
        self.assertIn(f"- 不明なメンバー: キャラ{self.session_voice(BOB)}", reply)

    async def test_display_name_is_escaped(self) -> None:
        await self.join(ALICE)
        self.names[ALICE] = "a*b_c"
        _, reply = await self.members()
        self.assertIn(r"a\*b\_c", reply)

    async def test_without_catalog_shows_ids_and_no_credit(self) -> None:
        await self.join(ALICE)
        self.cog.catalog = None
        _, reply = await self.members()
        self.assertIn(f"ID {self.session_voice(ALICE)}", reply)
        self.assertNotIn("VOICEVOX:", reply)

    async def test_more_than_twenty_members_are_summarized(self) -> None:
        await self.join(ALICE)
        self.seed(20)
        _, reply = await self.members()
        lines = reply.split("\n")
        self.assertIn("（21 人）", lines[0])
        self.assertEqual(len(lines), 1 + 20 + 1)
        self.assertEqual(lines[-1], "他 1 人")

    async def test_long_lines_are_cut_within_the_message_limit(self) -> None:
        await self.join(ALICE)
        self.seed(19)
        self.cog.catalog = (Voice(3, "あ" * 150, "ノーマル"),)
        _, reply = await self.members()
        lines = reply.split("\n")
        self.assertLessEqual(len(reply), 1900)
        shown = len(lines) - 2
        self.assertLess(shown, 20)
        self.assertEqual(lines[-1], f"他 {20 - shown} 人")

    async def test_ephemeral_without_defer(self) -> None:
        await self.join(ALICE)
        interaction, _ = await self.members()
        interaction.response.defer.assert_not_awaited()
        self.assertTrue(
            interaction.response.send_message.await_args.kwargs["ephemeral"]
        )

    async def test_does_not_wait_for_the_lock(self) -> None:
        await self.join(ALICE)
        async with self.cog.lock:
            async with asyncio.timeout(1):
                _, reply = await self.members()
        self.assertIn("（1 人）", reply)


class VoiceAssignmentTest(VoiceTestCase):
    async def test_post_is_synthesized_as_body_only_with_the_authors_voice(
        self,
    ) -> None:
        await self.join(ALICE)
        await self.join(BOB)
        await self.cog.on_message(self.message(BOB, "こんにちは"))
        await wait_until(lambda: self.client.synthesize.call_count == 1)
        self.assertEqual(
            self.client.synthesize.call_args.args,
            ("こんにちは", self.session_voice(BOB)),
        )
        self.voice_client.finish()

    async def test_participants_get_distinct_voices_until_the_pool_runs_out(
        self,
    ) -> None:
        for user in (ALICE, BOB, CAROL):
            await self.join(user)
        voices = {self.session_voice(user) for user in (ALICE, BOB, CAROL)}
        self.assertEqual(voices, set(POOL))

    async def test_simultaneous_joins_do_not_share_a_voice(self) -> None:
        await asyncio.gather(self.join(ALICE), self.join(BOB))
        self.assertNotEqual(self.session_voice(ALICE), self.session_voice(BOB))

    async def test_join_reply_shows_the_voice_with_credit(self) -> None:
        reply = await self.join(ALICE)
        voice = self.session_voice(ALICE)
        self.assertIn(f"声: キャラ{voice}（ノーマル）（VOICEVOX:キャラ{voice}）", reply)

    async def test_saved_voice_is_used(self) -> None:
        self.save(ALICE, 11)
        reply = await self.join(ALICE)
        self.assertEqual(self.session_voice(ALICE), 11)
        self.assertIn("キャラ11", reply)

    async def test_saved_voice_in_use_goes_to_the_earlier_participant(self) -> None:
        await self.join(ALICE)
        taken = self.session_voice(ALICE)
        self.save(BOB, taken)
        reply = await self.join(BOB)
        self.assertEqual(self.session_voice(ALICE), taken)
        self.assertNotEqual(self.session_voice(BOB), taken)
        self.assertIn(self.session_voice(BOB), POOL)
        self.assertIn("使用中", reply)

    async def test_saved_voice_is_kept_as_duplicate_when_the_pool_is_full(
        self,
    ) -> None:
        for user in (ALICE, BOB, CAROL):
            await self.join(user)
        taken = self.session_voice(ALICE)
        self.save(ADMIN, taken)
        await self.join(ADMIN)
        self.assertEqual(self.session_voice(ADMIN), taken)

    async def test_saved_voice_missing_from_catalog_falls_back_and_keeps_the_row(
        self,
    ) -> None:
        self.save(ALICE, 99)
        reply = await self.join(ALICE)
        self.assertIn(self.session_voice(ALICE), POOL)
        self.assertIn("ID 99", reply)
        self.assertEqual(self.saved(ALICE), 99)

    async def test_preference_read_failure_does_not_block_join(self) -> None:
        with (
            mock.patch.object(self.db, "find_tts_voice", side_effect=RepositoryError),
            self.assertLogs("ctfbot", "ERROR"),
        ):
            reply = await self.join(ALICE)
        self.assertIn("開始しました", reply)
        self.assertIn(self.session_voice(ALICE), POOL)

    async def test_voice_is_kept_while_others_leave_and_after_rejoining(self) -> None:
        await self.join(ALICE)
        await self.join(BOB)
        alice = self.session_voice(ALICE)
        await self.run_command(self.cog.leave, self.interaction(BOB))
        self.assertEqual(self.session_voice(ALICE), alice)
        await self.run_command(self.cog.leave, self.interaction(ALICE, manage=False))
        await self.join(ALICE)
        self.assertEqual(self.session_voice(ALICE), alice)

    async def test_rejoining_while_opted_in_keeps_the_voice(self) -> None:
        await self.join(ALICE)
        voice = self.session_voice(ALICE)
        self.save(ALICE, 11)
        await self.join(ALICE)
        self.assertEqual(self.session_voice(ALICE), voice)

    async def test_leaving_the_channel_releases_the_voice(self) -> None:
        await self.join(ALICE)
        await self.join(BOB)
        self.voice_of[ALICE] = self.channels[CHANNEL_B]
        await self.cog.on_voice_state_update(
            self.member(ALICE), self.voice_state(CHANNEL_A), self.voice_state(CHANNEL_B)
        )
        assert self.cog.session is not None
        self.assertNotIn(ALICE, self.cog.session.voices)


class VoiceSetTest(VoiceTestCase):
    async def test_set_saves_without_a_session(self) -> None:
        reply = await self.vset(ALICE, "11", None)
        self.assertIn("キャラ11（ノーマル）（VOICEVOX:キャラ11） に設定しました", reply)
        self.assertNotIn("現在の読み上げ", reply)
        self.assertEqual(self.saved(ALICE), 11)

    async def test_set_accepts_an_exact_label(self) -> None:
        await self.vset(ALICE, "キャラ８（ノーマル）", None)
        self.assertEqual(self.saved(ALICE), 8)

    async def test_set_applies_immediately_but_queued_posts_keep_the_old_voice(
        self,
    ) -> None:
        release = threading.Event()
        used: list[int] = []

        def synth(text: str, speaker_id: int) -> bytes:
            used.append(speaker_id)
            release.wait(2)
            return b"RIFFdata"

        self.client.synthesize.side_effect = synth
        await self.join(ALICE)
        old = self.session_voice(ALICE)
        new = 11
        await self.cog.on_message(self.message(ALICE, message_id=1))
        await self.cog.on_message(self.message(ALICE, message_id=2))
        reply = await self.vset(ALICE, str(new))
        self.assertIn("現在の読み上げにも反映しました", reply)
        self.assertEqual(self.session_voice(ALICE), new)
        await self.cog.on_message(self.message(ALICE, message_id=3))
        release.set()
        async with asyncio.timeout(2):
            while len(used) < 3:
                if self.voice_client.playing:
                    self.voice_client.finish()
                await asyncio.sleep(0.005)
        self.assertEqual(used, [old, old, new])

    async def test_set_to_a_voice_in_use_saves_but_keeps_the_session_voice(
        self,
    ) -> None:
        await self.join(ALICE)
        await self.join(BOB)
        bob = self.session_voice(BOB)
        taken = self.session_voice(ALICE)
        reply = await self.vset(BOB, str(taken))
        self.assertIn("使用中", reply)
        self.assertIn(f"キャラ{bob}", reply)
        self.assertEqual(self.saved(BOB), taken)
        self.assertEqual(self.session_voice(BOB), bob)

    async def test_unknown_input_is_not_saved(self) -> None:
        for query in ("存在しない", "999"):
            with self.subTest(query=query):
                reply = await self.vset(ALICE, query, None)
                self.assertEqual(reply, "声が見つかりません。候補から選んでください。")
                self.assertIsNone(self.saved(ALICE))

    async def test_unknown_id_triggers_one_forced_refresh(self) -> None:
        await self.vset(ALICE, "999", None)
        self.assertEqual(self.client.fetch_voices.call_count, 2)

    async def test_catalog_failure_is_not_saved(self) -> None:
        self.client.fetch_voices.side_effect = ExternalAPIError("down")
        with self.assertLogs("ctfbot", "WARNING"):
            reply = await self.vset(ALICE, "3", None)
        self.assertEqual(reply, "声の一覧を取得できませんでした。")
        self.assertIsNone(self.saved(ALICE))

    async def test_write_failure_changes_neither_db_nor_session(self) -> None:
        await self.join(ALICE)
        before = self.session_voice(ALICE)
        with (
            mock.patch.object(self.db, "upsert_tts_voice", side_effect=RepositoryError),
            self.assertLogs("ctfbot", "ERROR"),
        ):
            reply = await self.vset(ALICE, "11")
        self.assertEqual(reply, "声の設定を保存できませんでした。")
        self.assertIsNone(self.saved(ALICE))
        self.assertEqual(self.session_voice(ALICE), before)


class VoiceConcurrencyTest(VoiceTestCase):
    def block_first_write(self) -> tuple[threading.Event, threading.Event, list[int]]:
        entered, release = threading.Event(), threading.Event()
        writes: list[int] = []
        real = self.db.upsert_tts_voice

        def upsert(user_id: int, speaker_id: int, updated_at_unix: int) -> None:
            writes.append(speaker_id)
            if len(writes) == 1:
                entered.set()
                release.wait(2)
            real(user_id, speaker_id, updated_at_unix)

        patcher = mock.patch.object(self.db, "upsert_tts_voice", side_effect=upsert)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(release.set)
        return entered, release, writes

    async def test_concurrent_sets_leave_db_and_session_in_agreement(self) -> None:
        await self.join(ALICE)
        entered, release, writes = self.block_first_write()
        first = asyncio.create_task(self.vset(ALICE, "11"))
        await wait_until(entered.is_set)
        second = asyncio.create_task(self.vset(ALICE, "1"))
        await asyncio.sleep(0.05)
        self.assertEqual(writes, [11])
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(writes, [11, 1])
        self.assertEqual(self.saved(ALICE), self.session_voice(ALICE))
        self.assertEqual(self.session_voice(ALICE), 1)

    async def test_reset_after_a_blocked_set_wins_in_both_places(self) -> None:
        await self.join(ALICE)
        entered, release, _ = self.block_first_write()
        first = asyncio.create_task(self.vset(ALICE, "11"))
        await wait_until(entered.is_set)
        second = asyncio.create_task(self.vreset(ALICE))
        await asyncio.sleep(0.05)
        release.set()
        await asyncio.gather(first, second)
        self.assertIsNone(self.saved(ALICE))
        self.assertIn(self.session_voice(ALICE), POOL)

    async def test_set_waiting_for_join_applies_to_the_new_session(self) -> None:
        connecting = asyncio.Event()

        async def slow_connect(**_: object) -> FakeVoiceClient:
            connecting.set()
            await asyncio.sleep(0.05)
            return self.voice_client

        self.channels[CHANNEL_A].connect.side_effect = slow_connect
        joined = asyncio.create_task(self.join(ALICE))
        await connecting.wait()
        await self.vset(ALICE, "11")
        await joined
        self.assertEqual(self.session_voice(ALICE), 11)
        self.assertEqual(self.saved(ALICE), 11)

    async def test_catalog_fetch_does_not_hold_the_session_lock(self) -> None:
        await self.join(ALICE)
        release = threading.Event()
        started = threading.Event()

        def slow_fetch() -> tuple[Voice, ...]:
            started.set()
            release.wait(2)
            return VOICES

        self.addCleanup(release.set)
        self.client.fetch_voices.side_effect = slow_fetch
        pending = asyncio.create_task(self.vset(BOB, "999", None))
        await wait_until(started.is_set)
        async with asyncio.timeout(1):
            await self.join(CAROL)
        self.assertIn(self.session_voice(CAROL), POOL)
        release.set()
        await pending


class VoiceResetShowTest(VoiceTestCase):
    async def test_reset_returns_to_auto_and_applies_immediately(self) -> None:
        self.save(ALICE, 11)
        await self.join(ALICE)
        self.assertEqual(self.session_voice(ALICE), 11)
        reply = await self.vreset(ALICE)
        self.assertIn("自動に戻しました", reply)
        self.assertIsNone(self.saved(ALICE))
        self.assertIn(self.session_voice(ALICE), POOL)
        self.assertIn(f"キャラ{self.session_voice(ALICE)}", reply)

    async def test_reset_without_preference(self) -> None:
        self.assertEqual(await self.vreset(ALICE), "声は既に自動です。")

    async def test_reset_failure(self) -> None:
        with (
            mock.patch.object(self.db, "delete_tts_voice", side_effect=RepositoryError),
            self.assertLogs("ctfbot", "ERROR"),
        ):
            reply = await self.vreset(ALICE)
        self.assertEqual(reply, "声の設定を戻せませんでした。")

    async def test_show_auto_and_saved(self) -> None:
        self.assertIn("自動（通常は", await self.vshow(ALICE))
        self.save(ALICE, 11)
        await self.cog._refresh_catalog()
        reply = await self.vshow(ALICE)
        self.assertIn("声の設定: キャラ11（ノーマル）（VOICEVOX:キャラ11）", reply)
        self.assertNotIn("現在の読み上げ", reply)

    async def test_show_explains_a_session_voice_that_differs(self) -> None:
        await self.join(ALICE)
        self.save(BOB, self.session_voice(ALICE))
        await self.join(BOB)
        reply = await self.vshow(BOB)
        self.assertIn("現在の読み上げ", reply)
        self.assertIn("使用中", reply)

    async def test_show_without_catalog_uses_ids(self) -> None:
        self.client.fetch_voices.side_effect = ExternalAPIError("down")
        self.save(ALICE, 11)
        with self.assertLogs("ctfbot", "WARNING"):
            await self.join(ALICE)
        reply = await self.vshow(ALICE)
        self.assertIn("声の設定: ID 11", reply)
        self.assertNotIn("VOICEVOX:", reply)

    async def test_show_read_failure(self) -> None:
        with (
            mock.patch.object(self.db, "find_tts_voice", side_effect=RepositoryError),
            self.assertLogs("ctfbot", "ERROR"),
        ):
            reply = await self.vshow(ALICE)
        self.assertEqual(reply, "声の設定を読み込めませんでした。")


class CatalogTest(VoiceTestCase):
    async def test_concurrent_refreshes_fetch_once(self) -> None:
        await asyncio.gather(*(self.cog._refresh_catalog() for _ in range(5)))
        self.assertEqual(self.client.fetch_voices.call_count, 1)

    async def test_failure_backs_off_and_keeps_the_stale_catalog(self) -> None:
        now = [0.0]
        self.cog.clock = lambda: now[0]
        await self.cog._refresh_catalog()
        self.client.fetch_voices.side_effect = ExternalAPIError("down")
        now[0] = CATALOG_TTL_SECONDS + 1
        with self.assertLogs("ctfbot", "WARNING"):
            await self.cog._refresh_catalog()
        self.assertEqual(self.cog.catalog, VOICES)
        calls = self.client.fetch_voices.call_count
        now[0] += CATALOG_RETRY_SECONDS - 1
        await self.cog._refresh_catalog()
        self.assertEqual(self.client.fetch_voices.call_count, calls)
        now[0] += 2
        with self.assertLogs("ctfbot", "WARNING"):
            await self.cog._refresh_catalog()
        self.assertEqual(self.client.fetch_voices.call_count, calls + 1)

    async def test_fresh_catalog_is_reused(self) -> None:
        await self.cog._refresh_catalog()
        await self.cog._refresh_catalog()
        self.assertEqual(self.client.fetch_voices.call_count, 1)

    async def test_autocomplete_answers_from_memory_and_starts_a_refresh(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)

        def slow_fetch() -> tuple[Voice, ...]:
            release.wait(2)
            return VOICES

        self.client.fetch_voices.side_effect = slow_fetch
        interaction = self.interaction(ALICE)
        async with asyncio.timeout(1):
            choices = await cast(Any, self.cog).voice_set_autocomplete(interaction, "")
        self.assertEqual(choices, [])
        release.set()
        assert self.cog.catalog_task is not None
        await self.cog.catalog_task
        choices = await cast(Any, self.cog).voice_set_autocomplete(
            interaction, "キャラ1"
        )
        self.assertEqual(
            [(c.name, c.value) for c in choices],
            [("キャラ1（ノーマル）", "1"), ("キャラ11（ノーマル）", "11")],
        )

    async def test_unload_cancels_the_background_refresh(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)
        self.client.fetch_voices.side_effect = lambda: release.wait(2)
        await self.cog.cog_load()
        task = self.cog.catalog_task
        assert task is not None
        await self.cog.cog_unload()
        await asyncio.sleep(0.01)
        self.assertTrue(task.cancelled())


class SetupTest(unittest.IsolatedAsyncioTestCase):
    def bot(self, url: str | None) -> commands.Bot:
        bot = commands.Bot(
            command_prefix=commands.when_mentioned, intents=discord.Intents.default()
        )
        cast(Any, bot).runtime = BotRuntime(
            settings=cast(
                Any,
                SimpleNamespace(
                    guild_id=GUILD_ID,
                    tts_max_chars=200,
                    tts_voicevox_url=url,
                    tts_speaker_ids=POOL,
                ),
            ),
            db=mock.Mock(),
        )
        return bot

    async def test_disabled_adds_no_cog_and_no_commands(self) -> None:
        bot = self.bot(None)
        await tts_cog.setup(bot)
        self.assertIsNone(bot.get_cog("TTS"))
        self.assertEqual(bot.tree.get_commands(), [])

    async def test_enabled_registers_commands_with_help(self) -> None:
        bot = self.bot("http://127.0.0.1:50021")
        with (
            mock.patch.object(tts_cog, "check_playback_ready", return_value=True),
            mock.patch.object(
                tts_cog.VoicevoxClient, "fetch_voices", return_value=VOICES
            ),
            self.assertLogs("ctfbot", "ERROR") as logs,
        ):
            await tts_cog.setup(bot)
        self.assertIn("Message Content Intent", logs.output[0])
        groups = {command.name: command for command in bot.tree.get_commands()}
        self.assertEqual(set(groups), {"read"})
        read_group = groups["read"]
        assert isinstance(read_group, app_commands.Group)
        self.assertIn("help", read_group.extras)
        commands_by_name = {command.name: command for command in read_group.commands}
        self.assertEqual(
            set(commands_by_name),
            {"join", "leave", "skip", "stop", "members", "voice"},
        )
        for command in commands_by_name.values():
            self.assertIn("help", command.extras)
        voice_group = commands_by_name["voice"]
        assert isinstance(voice_group, app_commands.Group)
        voice_commands = {command.name: command for command in voice_group.commands}
        self.assertEqual(set(voice_commands), {"show", "set", "reset"})
        for command in voice_commands.values():
            self.assertIn("help", command.extras)
        set_command = voice_commands["set"]
        assert isinstance(set_command, app_commands.Command)
        parameter = set_command.get_parameter("voice")
        assert parameter is not None
        self.assertIsNotNone(parameter.autocomplete)
        self.assertIsInstance(bot.get_cog("TTS"), TTS)
        await bot.remove_cog("TTS")
