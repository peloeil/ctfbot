import requests

from ctfbot.errors import ExternalAPIError
from ctfbot.features.tts.service import Voice

TIMEOUT = (5, 30)
SPEAKERS_TIMEOUT = (3, 10)
# Styles without "type" come from older engines; sing/frame_decode cannot go
# through /audio_query
TALK_STYLE_TYPES = frozenset({"talk", "streaming_talk"})


class VoicevoxClient:
    def __init__(self, base_url: str, *, speed_scale: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.speed_scale = speed_scale

    def fetch_voices(self) -> tuple[Voice, ...]:
        try:
            response = requests.get(
                f"{self.base_url}/speakers", timeout=SPEAKERS_TIMEOUT
            )
            response.raise_for_status()
            speakers = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ExternalAPIError("VOICEVOX speakers request failed.") from exc

        if not isinstance(speakers, list):
            raise ExternalAPIError("Unexpected VOICEVOX speakers response.")
        # A malformed element fails the whole response instead of being skipped
        voices: dict[int, Voice] = {}
        try:
            for speaker in speakers:
                name = speaker["name"]
                styles = speaker["styles"]
                if not isinstance(name, str) or not isinstance(styles, list):
                    raise TypeError
                for style in styles:
                    style_id = style["id"]
                    style_name = style["name"]
                    style_type = style.get("type")
                    if (
                        not isinstance(style_id, int)
                        or isinstance(style_id, bool)
                        or not isinstance(style_name, str)
                        or not (style_type is None or isinstance(style_type, str))
                    ):
                        raise TypeError
                    if style_type is None or style_type in TALK_STYLE_TYPES:
                        voices.setdefault(style_id, Voice(style_id, name, style_name))
        except (TypeError, KeyError, AttributeError) as exc:
            raise ExternalAPIError("Unexpected VOICEVOX speakers response.") from exc
        if not voices:
            raise ExternalAPIError("VOICEVOX returned no talk voices.")
        return tuple(voices.values())

    def synthesize(self, text: str, speaker_id: int) -> bytes:
        try:
            query_response = requests.post(
                f"{self.base_url}/audio_query",
                params={"text": text, "speaker": speaker_id},
                timeout=TIMEOUT,
            )
            query_response.raise_for_status()
            query = query_response.json()
            if not isinstance(query, dict):
                raise ExternalAPIError("Unexpected VOICEVOX audio query.")
            query["speedScale"] = self.speed_scale
            synthesis_response = requests.post(
                f"{self.base_url}/synthesis",
                params={"speaker": speaker_id},
                json=query,
                timeout=TIMEOUT,
            )
            synthesis_response.raise_for_status()
            audio = synthesis_response.content
        except (requests.RequestException, ValueError) as exc:
            raise ExternalAPIError("VOICEVOX request failed.") from exc

        if not audio.startswith(b"RIFF"):
            raise ExternalAPIError("VOICEVOX returned invalid audio.")
        return audio
