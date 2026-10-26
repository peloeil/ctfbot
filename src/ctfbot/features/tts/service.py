import hashlib
import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

MAX_VOICE_CHOICES = 25
# The full-width form is what a Japanese IME types by default
SILENT_PREFIXES = (";", "\uff1b")

_FENCED_CODE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_SPOILER = re.compile(r"\|\|.*?\|\|", re.DOTALL)
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\(\s*<?https?://[^)\s]*>?\s*\)")
_URL = re.compile(r"<?https?://[^\s<>]+>?")
_DISCORD_TOKEN = re.compile(
    r"<a?:\w+:\d+>"  # custom emoji
    r"|<@[!&]?\d+>|<#\d+>"  # user, role, channel
    r"|</[^>\s]+:\d+>"  # command
    r"|<t:-?\d+(?::[a-zA-Z])?>"  # timestamp
    r"|@everyone|@here"
)
_LINE_PREFIX = re.compile(r"^\s*(?:>{1,3}|#{1,3}|[-*+]|\d+[.)])\s+")
_DECORATION = re.compile(r"\*+|~~|__|`|\|\|")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_REPEATED_CHAR = re.compile(r"(.)\1{3,}", re.DOTALL)
_SPACES = re.compile(r"[ \t　]+")


@dataclass(frozen=True, slots=True)
class SpeechItem:
    message_id: int
    author_id: int
    text: str
    speaker_id: int


@dataclass(frozen=True, slots=True)
class Voice:
    style_id: int
    speaker_name: str
    style_name: str

    @property
    def label(self) -> str:
        return f"{self.speaker_name}（{self.style_name}）"

    @property
    def credit(self) -> str:
        return f"VOICEVOX:{self.speaker_name}"


def normalize_text(text: str) -> str:
    text = _FENCED_CODE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _SPOILER.sub(" ", text)
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    text = _DISCORD_TOKEN.sub(" ", text)
    text = _ZERO_WIDTH.sub("", text)
    lines = []
    for line in text.splitlines():
        line = _DECORATION.sub("", _LINE_PREFIX.sub("", line))
        line = _SPACES.sub(" ", line).strip()
        if line:
            lines.append(line)
    joined = "、".join(lines)
    return _REPEATED_CHAR.sub(lambda match: match.group(1) * 3, joined)


def build_speech_text(content: str, max_chars: int) -> str | None:
    if content.lstrip().startswith(SILENT_PREFIXES):
        return None
    return normalize_text(content)[:max_chars].strip() or None


def mentions_user(content: str, user_id: int) -> bool:
    return re.search(rf"<@!?{user_id}>", content) is not None


def assign_auto_voice(
    user_id: int, pool: Sequence[int], usage: Mapping[int, int]
) -> int:
    """Pick a pool voice by a stable per-user hash, preferring unused voices.

    sha256 keeps the result identical across restarts, and avoids the skew of
    the low bits of a snowflake.
    """
    start = int.from_bytes(hashlib.sha256(str(user_id).encode()).digest()[:8]) % len(
        pool
    )
    order = [pool[(start + offset) % len(pool)] for offset in range(len(pool))]
    # min() keeps the first of equal counts, i.e. the earliest in rotation order
    return min(order, key=lambda voice_id: usage.get(voice_id, 0))


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


# VOICEVOX の話者には多数の感情・演技スタイルがある。選択候補は通常の
# 読み上げに使うスタイルだけに絞り、似た名前のバリエーションで埋めない。
_NORMAL_STYLE_NAMES = frozenset({"ノーマル", "ふつう", "normal", "通常", "標準"})


def _is_normal_voice(voice: Voice) -> bool:
    return _fold(voice.style_name).strip() in _NORMAL_STYLE_NAMES


def resolve_voice(
    query: str, voices: Sequence[Voice], allowed_ids: Collection[int]
) -> Voice | None:
    """Resolve a style ID or an exact label among the allowed normal voices."""
    folded = _fold(query).strip()
    for voice in voices:
        if voice.style_id not in allowed_ids or not _is_normal_voice(voice):
            continue
        if folded == str(voice.style_id) or folded == _fold(voice.label):
            return voice
    return None


def filter_voices(
    query: str, voices: Sequence[Voice], allowed_ids: Collection[int]
) -> list[Voice]:
    """Return allowed normal-style voices matching the query, for autocomplete."""
    folded = _fold(query).strip()
    matched = [
        voice
        for voice in voices
        if voice.style_id in allowed_ids
        and _is_normal_voice(voice)
        and (folded in _fold(voice.label) or folded in str(voice.style_id))
    ]
    return matched[:MAX_VOICE_CHOICES]
