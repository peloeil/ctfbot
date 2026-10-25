import asyncio
import contextlib
import io
import shutil
import time
from collections import Counter
from collections.abc import Callable, Collection

import discord
from discord import app_commands
from discord.ext import commands

from ctfbot.errors import ExternalAPIError, RepositoryError, ServiceError
from ctfbot.features.tts.service import (
    SpeechItem,
    Voice,
    assign_auto_voice,
    build_speech_text,
    filter_voices,
    mentions_user,
    resolve_voice,
)
from ctfbot.features.tts.voicevox import VoicevoxClient
from ctfbot.helpers import (
    MAX_MESSAGE_CONTENT_LENGTH,
    require_guild,
    send_interaction,
)
from ctfbot.log import logger
from ctfbot.runtime import get_runtime

MAX_QUEUE_SIZE = 20
LEAVE_GRACE_SECONDS = 5.0
CONNECT_TIMEOUT_SECONDS = 15.0
CATALOG_TTL_SECONDS = 3600.0
CATALOG_RETRY_SECONDS = 60.0
MAX_LISTED_MEMBERS = 20


def check_playback_ready() -> bool:
    ready = True
    if shutil.which("ffmpeg") is None:
        logger.error("TTS requires ffmpeg, but it was not found in PATH")
        ready = False
    # discord.py exposes no public API to load libopus on demand
    if not discord.opus.is_loaded() and not discord.opus._load_default():
        logger.error("TTS requires libopus, but it could not be loaded")
        ready = False
    return ready


class _Session:
    """State of one voice connection. Discarded as a whole on disconnect."""

    def __init__(self, channel_id: int, voice_client: discord.VoiceClient) -> None:
        self.channel_id = channel_id
        self.voice_client = voice_client
        # Opted-in user ID -> VOICEVOX style ID, kept until the opt-in ends
        self.voices: dict[int, int] = {}
        self.queue: asyncio.Queue[SpeechItem] = asyncio.Queue(MAX_QUEUE_SIZE)
        # Bumped by /read stop so an item that is being synthesized is dropped too
        self.epoch = 0
        self.worker: asyncio.Task[None] | None = None
        self.grace: asyncio.Task[None] | None = None

    @property
    def opted_in(self) -> Collection[int]:
        return self.voices.keys()

    def usage(self, *, excluding: int) -> Counter[int]:
        return Counter(
            voice for user_id, voice in self.voices.items() if user_id != excluding
        )

    def drain_queue(self) -> None:
        self.epoch += 1
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return


def _is_in_channel(guild: discord.Guild, user_id: int, channel_id: int) -> bool:
    member = guild.get_member(user_id)
    voice = member.voice if member is not None else None
    return (
        voice is not None
        and voice.channel is not None
        and voice.channel.id == channel_id
    )


def _can_manage(interaction: discord.Interaction) -> bool:
    permissions = getattr(interaction.user, "guild_permissions", None)
    return permissions is not None and permissions.manage_guild


class TTS(commands.Cog):
    read = app_commands.Group(
        name="read",
        description="VC のテキストチャットを読み上げます。",
        extras={
            "help": "bot が接続している VC のテキストチャットを VOICEVOX で"
            "読み上げます。読み上げるのは `/read join` した人の投稿の本文だけで、"
            "VC から離れると対象から外れます。参加者ごとに声が変わり、"
            "声は `/read voice` で選べます。"
            "参加者と声は `/read members` で確認できます。\n"
            "VOICEVOX を使用しています。"
            "クレジットは `/read voice show` で確認できます。"
        },
    )
    voice = app_commands.Group(
        name="voice",
        description="読み上げの声を確認・設定します。",
        parent=read,
        extras={
            "help": "読み上げの声を確認・設定します。声を設定していない場合は、"
            "参加者ごとに自動で割り当てます。読み上げ中でなくても設定できます。"
        },
    )

    def __init__(
        self,
        bot: commands.Bot,
        client: VoicevoxClient,
        *,
        grace_seconds: float = LEAVE_GRACE_SECONDS,
        playback_ready: bool | None = None,
    ) -> None:
        settings = get_runtime(bot).settings
        self.bot = bot
        self.guild_id = settings.guild_id
        self.max_chars = settings.tts_max_chars
        self.pool = settings.tts_speaker_ids
        self.db = get_runtime(bot).db
        self.client = client
        self.grace_seconds = grace_seconds
        self.lock = asyncio.Lock()
        self.session: _Session | None = None
        self.clock: Callable[[], float] = time.monotonic
        self.catalog: tuple[Voice, ...] | None = None
        self.catalog_fetched_at = 0.0
        self.catalog_failed_at: float | None = None
        self.catalog_lock = asyncio.Lock()
        self.catalog_task: asyncio.Task[None] | None = None
        if not bot.intents.message_content:
            logger.error("TTS requires the Message Content Intent, but it is disabled")
        self.playback_ready = (
            check_playback_ready() if playback_ready is None else playback_ready
        )

    async def cog_load(self) -> None:
        self._start_catalog_refresh()

    async def cog_unload(self) -> None:
        if self.catalog_task is not None:
            self.catalog_task.cancel()
        async with self.lock:
            if self.session is not None:
                await self._teardown(self.session)

    def _catalog_is_fresh(self) -> bool:
        return (
            self.catalog is not None
            and self.clock() - self.catalog_fetched_at < CATALOG_TTL_SECONDS
        )

    def _start_catalog_refresh(self) -> None:
        """Refresh in the background; single-flight."""
        if self.catalog_task is None or self.catalog_task.done():
            self.catalog_task = asyncio.create_task(self._refresh_catalog_quietly())

    async def _refresh_catalog_quietly(self) -> None:
        try:
            await self._refresh_catalog()
        except Exception:
            logger.exception("Unexpected error while refreshing the TTS voice catalog")

    async def _refresh_catalog(self, *, force: bool = False) -> None:
        """Update the catalog if stale. Never call this while holding self.lock."""
        # Skip the lock when fresh so a refresh in flight does not delay callers
        if not force and self._catalog_is_fresh():
            return
        async with self.catalog_lock:
            now = self.clock()
            if not force and self._catalog_is_fresh():
                return
            if (
                self.catalog_failed_at is not None
                and now - self.catalog_failed_at < CATALOG_RETRY_SECONDS
            ):
                return
            try:
                voices = await asyncio.to_thread(self.client.fetch_voices)
            except ExternalAPIError:
                logger.warning("Failed to fetch the VOICEVOX voice catalog")
                self.catalog_failed_at = now
                return
            first = self.catalog is None
            self.catalog = voices
            self.catalog_fetched_at = now
            self.catalog_failed_at = None
            if first:
                self._log_missing_pool_voices(voices)

    def _log_missing_pool_voices(self, voices: tuple[Voice, ...]) -> None:
        known = {voice.style_id for voice in voices}
        missing = [voice_id for voice_id in self.pool if voice_id not in known]
        if len(missing) == len(self.pool):
            logger.error("None of TTS_SPEAKER_IDS exist in VOICEVOX: %s", missing)
        elif missing:
            logger.warning("TTS_SPEAKER_IDS not found in VOICEVOX: %s", missing)

    def _effective_pool(self) -> tuple[int, ...]:
        if self.catalog is None:
            return self.pool
        known = {voice.style_id for voice in self.catalog}
        return tuple(v for v in self.pool if v in known) or self.pool

    def _find_voice(self, speaker_id: int) -> Voice | None:
        if self.catalog is None:
            return None
        return next((v for v in self.catalog if v.style_id == speaker_id), None)

    def _label(self, speaker_id: int) -> str:
        voice = self._find_voice(speaker_id)
        return voice.label if voice is not None else f"ID {speaker_id}"

    def _describe(self, speaker_id: int) -> str:
        voice = self._find_voice(speaker_id)
        if voice is None:
            return f"ID {speaker_id}"
        return f"{voice.label}（{voice.credit}）"

    def _is_current(self, session: _Session) -> bool:
        return self.session is session

    async def _teardown(self, session: _Session, *, disconnect: bool = True) -> None:
        """Discard the session. The caller must hold the lock."""
        if self.session is session:
            self.session = None
        current = asyncio.current_task()
        for task in (session.worker, session.grace):
            if task is not None and task is not current:
                task.cancel()
        session.drain_queue()
        voice_client = session.voice_client
        if voice_client.is_playing():
            voice_client.stop()
        if disconnect:
            await self._force_disconnect(voice_client)

    async def _force_disconnect(self, voice_client: discord.VoiceProtocol) -> None:
        try:
            await voice_client.disconnect(force=True)
        except Exception:
            logger.exception("Failed to disconnect from voice channel")

    def _schedule_leave(self, session: _Session) -> None:
        """Leave once nobody is opted in. The caller must hold the lock."""
        if session.grace is None:
            session.grace = asyncio.create_task(self._leave_after_grace(session))

    async def _leave_after_grace(self, session: _Session) -> None:
        await asyncio.sleep(self.grace_seconds)
        async with self.lock:
            if self._is_current(session) and not session.opted_in:
                session.grace = None
                await self._teardown(session)

    async def _run_worker(self, session: _Session) -> None:
        while True:
            item = await session.queue.get()
            try:
                await self._speak(session, item)
            except discord.opus.OpusNotLoaded:
                logger.error("libopus is not loaded; ending the TTS session")
                async with self.lock:
                    if self._is_current(session):
                        await self._teardown(session)
                return
            except Exception:
                logger.exception(
                    "Unexpected TTS error for message id=%s", item.message_id
                )

    async def _speak(self, session: _Session, item: SpeechItem) -> None:
        epoch = session.epoch
        try:
            audio = await asyncio.to_thread(
                self.client.synthesize, item.text, item.speaker_id
            )
        except ExternalAPIError:
            logger.warning("TTS synthesis failed for message id=%s", item.message_id)
            return
        if not self._is_current(session) or session.epoch != epoch:
            return

        loop = asyncio.get_running_loop()
        finished: asyncio.Future[Exception | None] = loop.create_future()

        def complete(error: Exception | None) -> None:
            if not finished.done():
                finished.set_result(error)

        def after(error: Exception | None) -> None:
            # The player thread may call this after the loop has stopped
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(complete, error)

        # No await between the checks above and play(), so the session stays current
        source = None
        try:
            source = discord.FFmpegPCMAudio(io.BytesIO(audio), pipe=True)
            session.voice_client.play(source, after=after)
        except discord.ClientException:
            logger.warning("TTS playback failed for message id=%s", item.message_id)
            if source is not None:
                source.cleanup()
            return
        except discord.opus.OpusNotLoaded:
            if source is not None:
                source.cleanup()
            raise
        error = await finished
        if error is not None:
            logger.warning("TTS playback error for message id=%s", item.message_id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        session = self.session
        if (
            session is None
            or message.guild is None
            or message.guild.id != self.guild_id
            or message.author.bot
            or message.webhook_id is not None
            or message.type
            not in (discord.MessageType.default, discord.MessageType.reply)
            or self.bot.user is None
            or message.channel.id != session.channel_id
            or message.author.id not in session.opted_in
        ):
            return
        voice = getattr(message.author, "voice", None)
        if (
            voice is None
            or voice.channel is None
            or voice.channel.id != session.channel_id
        ):
            return
        if mentions_user(message.content, self.bot.user.id):
            return
        text = build_speech_text(message.content, self.max_chars)
        if text is None:
            return
        # Fixed at enqueue so a later voice change does not alter queued posts
        speaker_id = session.voices[message.author.id]
        try:
            session.queue.put_nowait(SpeechItem(message.id, text, speaker_id))
        except asyncio.QueueFull:
            logger.warning(
                "TTS queue is full; dropped message id=%s chars=%s",
                message.id,
                len(text),
            )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        session = self.session
        if session is None or member.guild.id != self.guild_id:
            return
        if self.bot.user is not None and member.id == self.bot.user.id:
            await self._on_bot_voice_state(session, before, after)
            return
        if member.id not in session.opted_in:
            return
        if after.channel is not None and after.channel.id == session.channel_id:
            return
        async with self.lock:
            if not self._is_current(session) or member.id not in session.opted_in:
                return
            session.voices.pop(member.id, None)
            if not session.opted_in:
                self._schedule_leave(session)

    async def _on_bot_voice_state(
        self, session: _Session, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if before.channel is None:
            return
        if after.channel is not None and after.channel.id == before.channel.id:
            return
        # Disconnected externally, or moved by an admin (the library keeps the
        # connection and only changes its channel). Reconnecting is not attempted.
        async with self.lock:
            if self._is_current(session):
                logger.info("Voice channel changed externally; ending the TTS session")
                await self._teardown(session)

    @read.command(
        name="join",
        description="VC のテキストチャットの読み上げを開始します。",
        extras={
            "help": "あなたを読み上げ対象に加え、bot が未接続なら今いる VC に"
            "接続します。対象の人が VC に居る間に VC のテキストチャットへ投稿した"
            "メッセージの本文を、あなた専用の声で VOICEVOX で読み上げます。"
            "声は `/read voice` で選べます。\n"
            "別の VC で読み上げ中の場合は参加できません。VC から離れると対象から外れ、"
            "再開するには再度実行してください。"
        },
    )
    async def join(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            reply = await self._join(interaction)
        except ServiceError as exc:
            reply = str(exc)
        await send_interaction(interaction, reply)

    async def _join(self, interaction: discord.Interaction) -> str:
        guild = require_guild(interaction)
        voice = getattr(interaction.user, "voice", None)
        channel = voice.channel if voice is not None else None
        if not isinstance(channel, discord.VoiceChannel):
            raise ServiceError("ボイスチャンネルに参加してから実行してください。")
        if not self.playback_ready:
            raise ServiceError("音声再生の準備ができていません。")
        permissions = channel.permissions_for(guild.me)
        if not (permissions.view_channel and permissions.connect and permissions.speak):
            raise ServiceError("bot にこの VC の閲覧・接続・発言の権限がありません。")

        user_id = interaction.user.id
        # Fetching can take seconds, so it must finish before taking the lock
        await self._refresh_catalog()
        notes: list[str] = []
        async with self.lock:
            session = self.session
            if session is None:
                session = await self._connect(guild, channel)
            elif session.channel_id != channel.id:
                raise ServiceError("既に別の VC で読み上げ中です。")
            if session.grace is not None:
                session.grace.cancel()
                session.grace = None
            if not _is_in_channel(guild, user_id, channel.id):
                if not session.opted_in:
                    self._schedule_leave(session)
                raise ServiceError("ボイスチャンネルに参加してから実行してください。")
            if user_id not in session.voices:
                session.voices[user_id], notes = await self._assign_voice(
                    session, user_id
                )
            speaker_id = session.voices[user_id]
        return (
            f"✅ {channel.mention} のテキストチャットの読み上げを開始しました。"
            f"声: {self._describe(speaker_id)}" + "".join(f" {note}" for note in notes)
        )

    async def _assign_voice(
        self, session: _Session, user_id: int
    ) -> tuple[int, list[str]]:
        """Decide the session voice. The caller must hold the lock."""
        try:
            saved = await asyncio.to_thread(self.db.find_tts_voice, user_id)
        except RepositoryError:
            logger.exception("Failed to read the TTS voice preference")
            saved = None
            notes = ["声の設定を読み込めなかったため、自動の声を使います。"]
        else:
            notes = []
        usage = session.usage(excluding=user_id)
        pool = self._effective_pool()
        if saved is None:
            return assign_auto_voice(user_id, pool, usage), notes
        if self.catalog is not None and self._find_voice(saved) is None:
            notes.append(
                f"設定した声（ID {saved}）が見つからないため、自動の声を使います。"
            )
            return assign_auto_voice(user_id, pool, usage), notes
        if not usage[saved]:
            return saved, notes
        # The earlier participant keeps the voice; fall back only if a free one exists
        voice = assign_auto_voice(user_id, pool, usage)
        if usage[voice]:
            return saved, notes
        notes.append(
            f"設定した声 {self._label(saved)} は他の人が使用中のため、"
            f"この読み上げでは {self._label(voice)} を使います。"
        )
        return voice, notes

    async def _connect(
        self, guild: discord.Guild, channel: discord.VoiceChannel
    ) -> _Session:
        """Connect and create the session. The caller must hold the lock."""
        try:
            voice_client = await channel.connect(
                timeout=CONNECT_TIMEOUT_SECONDS, self_deaf=True
            )
        except (
            TimeoutError,
            discord.ClientException,
            discord.opus.OpusNotLoaded,
            RuntimeError,
        ):
            logger.exception("Failed to connect to voice channel %s", channel.id)
            if guild.voice_client is not None:
                await self._force_disconnect(guild.voice_client)
            raise ServiceError("ボイスチャンネルに接続できませんでした。") from None
        session = _Session(channel.id, voice_client)
        session.worker = asyncio.create_task(self._run_worker(session))
        self.session = session
        return session

    @read.command(
        name="leave",
        description="VC のテキストチャットの読み上げ対象から外れます。",
        extras={
            "help": "あなたを読み上げ対象から外します。対象が誰もいなくなったら"
            "bot は VC から切断します。\n"
            "サーバー管理権限を持つ人が実行すると、全員を対象から外して切断します。"
        },
    )
    async def leave(self, interaction: discord.Interaction) -> None:
        try:
            reply = await self._leave(interaction)
        except ServiceError as exc:
            reply = str(exc)
        await send_interaction(interaction, reply)

    async def _leave(self, interaction: discord.Interaction) -> str:
        require_guild(interaction)
        async with self.lock:
            session = self._require_session()
            if _can_manage(interaction):
                await self._teardown(session)
                return "✅ 読み上げを終了しました。"
            if interaction.user.id not in session.opted_in:
                raise ServiceError("読み上げの対象ではありません。")
            session.voices.pop(interaction.user.id, None)
            if session.opted_in:
                return "✅ 読み上げの対象から外れました。"
            await self._teardown(session)
            return "✅ 読み上げを終了しました。"

    @read.command(
        name="skip",
        description="再生中の読み上げをスキップします。",
        extras={
            "help": "再生中の読み上げを止めて、次の投稿へ進みます。"
            "読み上げの対象の人かサーバー管理権限を持つ人が実行できます。"
        },
    )
    async def skip(self, interaction: discord.Interaction) -> None:
        try:
            session = self._require_controllable_session(interaction)
            if not session.voice_client.is_playing():
                raise ServiceError("再生中の読み上げはありません。")
            session.voice_client.stop()
            reply = "⏭️ スキップしました。"
        except ServiceError as exc:
            reply = str(exc)
        await send_interaction(interaction, reply)

    @read.command(
        name="stop",
        description="読み上げを停止し、待機中の読み上げを破棄します。",
        extras={
            "help": "この機能の読み上げを止め、待機中の読み上げを破棄します。"
            "bot 全体の停止ではなく、VC への接続も維持します。"
            "読み上げの対象の人かサーバー管理権限を持つ人が実行できます。"
        },
    )
    async def stop(self, interaction: discord.Interaction) -> None:
        try:
            session = self._require_controllable_session(interaction)
            session.drain_queue()
            if session.voice_client.is_playing():
                session.voice_client.stop()
            reply = "⏹️ 読み上げを停止しました。"
        except ServiceError as exc:
            reply = str(exc)
        await send_interaction(interaction, reply)

    @read.command(
        name="members",
        description="読み上げの参加者と声を表示します。",
        extras={
            "help": "読み上げに参加している人と、それぞれの声を参加した順に"
            "表示します。VC に入っていなくても実行できます。表示は 20 人までで、"
            "それより多い場合は残りの人数だけを表示します。"
        },
    )
    async def members(self, interaction: discord.Interaction) -> None:
        try:
            reply = self._members(interaction)
        except ServiceError as exc:
            reply = str(exc)
        await send_interaction(interaction, reply)

    def _members(self, interaction: discord.Interaction) -> str:
        # No await, and no lock: a join in progress must not delay this reply
        guild = require_guild(interaction)
        session = self._require_session()
        channel = f"<#{session.channel_id}>"
        entries = list(session.voices.items())
        if not entries:
            return f"🔊 {channel} の読み上げ参加者はいません。まもなく切断します。"
        total = len(entries)
        message = f"🔊 {channel} の読み上げ参加者（{total} 人）"
        shown = 0
        for user_id, speaker_id in entries[:MAX_LISTED_MEMBERS]:
            member = guild.get_member(user_id)
            name = (
                discord.utils.escape_markdown(member.display_name)
                if member is not None
                else "不明なメンバー"
            )
            mark = "（あなた）" if user_id == interaction.user.id else ""
            line = f"\n- {name}{mark}: {self._label(speaker_id)}"
            rest = total - shown - 1
            tail = f"\n他 {rest} 人" if rest else ""
            if len(message + line + tail) > MAX_MESSAGE_CONTENT_LENGTH:
                break
            message += line
            shown += 1
        if shown < total:
            message += f"\n他 {total - shown} 人"
        return message

    @voice.command(
        name="show",
        description="読み上げの声の設定を確認します。",
        extras={
            "help": "保存している声の設定と、読み上げ中であれば現在使っている声を"
            "表示します。設定がなければ自動で割り当てられる声を表示します。"
            "VOICEVOX のクレジットも表示します。"
        },
    )
    async def voice_show(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            reply = await self._voice_show(interaction)
        except ServiceError as exc:
            reply = str(exc)
        await send_interaction(interaction, reply)

    async def _voice_show(self, interaction: discord.Interaction) -> str:
        require_guild(interaction)
        user_id = interaction.user.id
        try:
            saved = await asyncio.to_thread(self.db.find_tts_voice, user_id)
        except RepositoryError:
            logger.exception("Failed to read the TTS voice preference")
            raise ServiceError("声の設定を読み込めませんでした。") from None
        # No await from here on, so both values are read at one instant
        session = self.session
        current = session.voices.get(user_id) if session is not None else None
        if saved is not None:
            lines = [f"声の設定: {self._describe(saved)}"]
        else:
            auto = assign_auto_voice(user_id, self._effective_pool(), {})
            lines = [f"声の設定: 自動（通常は {self._describe(auto)}）"]
        if current is not None:
            line = f"現在の読み上げ: {self._describe(current)}"
            if saved is not None and current != saved:
                if self.catalog is not None and self._find_voice(saved) is None:
                    line += "（設定した声が見つからないため）"
                else:
                    line += "（設定した声は他の人が使用中のため）"
            lines.append(line)
        return "\n".join(lines)

    @voice.command(
        name="set",
        description="読み上げの声を設定します。",
        extras={
            "help": "読み上げに使う声を選んで保存します。読み上げに参加して"
            "いなくても設定できます。読み上げ中は、他の人が使っていない声なら"
            "すぐに反映します。使用中の声は保存だけして、次に参加したときに"
            "反映します。選べるのは VOICEVOX ENGINE が提供する声です。"
        },
    )
    @app_commands.describe(voice="声の名前または ID (候補から選択)")
    async def voice_set(self, interaction: discord.Interaction, voice: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            reply = await self._voice_set(interaction, voice)
        except ServiceError as exc:
            reply = str(exc)
        await send_interaction(interaction, reply)

    @voice_set.autocomplete("voice")
    async def voice_set_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        # Answered from memory only; Discord allows 3 seconds per keystroke
        if not self._catalog_is_fresh():
            self._start_catalog_refresh()
        return [
            app_commands.Choice(name=voice.label[:100], value=str(voice.style_id))
            for voice in filter_voices(current, self.catalog or ())
        ]

    async def _resolve_voice(self, query: str) -> Voice:
        await self._refresh_catalog()
        if self.catalog is None:
            raise ServiceError("声の一覧を取得できませんでした。")
        voice = resolve_voice(query, self.catalog)
        if voice is None and query.strip().isdecimal():
            # The ENGINE may have been updated since the catalog was cached
            await self._refresh_catalog(force=True)
            voice = resolve_voice(query, self.catalog)
        if voice is None:
            raise ServiceError("声が見つかりません。候補から選んでください。")
        return voice

    async def _voice_set(self, interaction: discord.Interaction, query: str) -> str:
        require_guild(interaction)
        chosen = await self._resolve_voice(query)
        user_id = interaction.user.id
        # The DB write and the session update must be one step under the lock,
        # or concurrent calls could leave them in different orders
        async with self.lock:
            try:
                await asyncio.to_thread(
                    self.db.upsert_tts_voice, user_id, chosen.style_id, int(time.time())
                )
            except RepositoryError:
                logger.exception("Failed to save the TTS voice preference")
                raise ServiceError("声の設定を保存できませんでした。") from None
            session = self.session
            current = session.voices.get(user_id) if session is not None else None
            if session is None or current is None:
                return f"✅ 声を {self._describe(chosen.style_id)} に設定しました。"
            if session.usage(excluding=user_id)[chosen.style_id]:
                return (
                    f"✅ 声を {self._describe(chosen.style_id)} に設定しました。"
                    f"この読み上げでは他の人が使用中のため、{self._describe(current)} "
                    "のままです。次に参加したときに反映します。"
                )
            session.voices[user_id] = chosen.style_id
        return (
            f"✅ 声を {self._describe(chosen.style_id)} に設定しました。"
            "現在の読み上げにも反映しました。"
        )

    @voice.command(
        name="reset",
        description="読み上げの声を自動に戻します。",
        extras={
            "help": "保存している声の設定を削除し、参加者ごとの自動割り当てに"
            "戻します。読み上げ中であれば、すぐに反映します。"
        },
    )
    async def voice_reset(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            reply = await self._voice_reset(interaction)
        except ServiceError as exc:
            reply = str(exc)
        await send_interaction(interaction, reply)

    async def _voice_reset(self, interaction: discord.Interaction) -> str:
        require_guild(interaction)
        user_id = interaction.user.id
        async with self.lock:
            try:
                deleted = await asyncio.to_thread(self.db.delete_tts_voice, user_id)
            except RepositoryError:
                logger.exception("Failed to delete the TTS voice preference")
                raise ServiceError("声の設定を戻せませんでした。") from None
            if not deleted:
                return "声は既に自動です。"
            session = self.session
            reply = "✅ 声の設定を自動に戻しました。"
            if session is not None and user_id in session.voices:
                auto = assign_auto_voice(
                    user_id, self._effective_pool(), session.usage(excluding=user_id)
                )
                session.voices[user_id] = auto
                reply += f"現在の読み上げでは {self._describe(auto)} を使います。"
        return reply

    def _require_session(self) -> _Session:
        if self.session is None:
            raise ServiceError("読み上げは開始されていません。")
        return self.session

    def _require_controllable_session(
        self, interaction: discord.Interaction
    ) -> _Session:
        require_guild(interaction)
        session = self._require_session()
        if interaction.user.id not in session.opted_in and not _can_manage(interaction):
            raise ServiceError(
                "読み上げの対象の人か、サーバー管理権限を持つ人のみ実行できます。"
            )
        return session


async def setup(bot: commands.Bot) -> None:
    settings = get_runtime(bot).settings
    if settings.tts_voicevox_url is None:
        logger.info("TTS disabled (TTS_VOICEVOX_URL is not set)")
        return
    client = VoicevoxClient(settings.tts_voicevox_url)
    await bot.add_cog(TTS(bot, client))
