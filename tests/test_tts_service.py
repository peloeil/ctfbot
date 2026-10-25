import unittest
from unittest import mock

import requests

from ctfbot.errors import ExternalAPIError
from ctfbot.features.tts.service import (
    Voice,
    assign_auto_voice,
    build_speech_text,
    filter_voices,
    mentions_user,
    normalize_text,
    resolve_voice,
)
from ctfbot.features.tts.voicevox import VoicevoxClient


class NormalizeTest(unittest.TestCase):
    def test_removed_elements_are_not_read(self) -> None:
        cases = {
            "fenced code": "前\n```py\nsecret = 1\n```\n後",
            "unclosed fence": "前\n```py\nsecret = 1",
            "inline code": "前 `secret` 後",
            "url": "前 https://example.com/secret?a=1 後",
            "angle url": "前 <https://example.com/secret> 後",
            "user mention": "前 <@123> <@!456> 後",
            "role mention": "前 <@&789> 後",
            "channel mention": "前 <#123> 後",
            "everyone": "前 @everyone @here 後",
            "command mention": "前 </roll:123456> 後",
            "timestamp": "前 <t:1700000000> <t:1700000000:R> 後",
            "emoji": "前 <:name:123> <a:dance:456> 後",
            "spoiler": "前 ||secret|| 後",
            "multiline spoiler": "前 ||sec\nret|| 後",
            "zero width": "前\u200b 後",
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                normalized = normalize_text(text)
                self.assertNotIn("secret", normalized)
                self.assertNotIn("sec", normalized)
                self.assertTrue(normalized.startswith("前"))
                self.assertTrue(normalized.endswith("後") or "```" in text)

    def test_spoiler_content_is_dropped_not_just_markers(self) -> None:
        self.assertEqual(normalize_text("答えは||flag{x}||です"), "答えは です")

    def test_zero_width_characters_are_removed(self) -> None:
        self.assertEqual(normalize_text("a\u200bb\ufeffc"), "abc")

    def test_markdown_link_keeps_label_only(self) -> None:
        self.assertEqual(
            normalize_text("[公式](https://example.com/a_b) を見て"), "公式 を見て"
        )

    def test_markdown_decoration_is_removed(self) -> None:
        self.assertEqual(
            normalize_text("**太字** ~~消~~ __下線__ *斜体*"), "太字 消 下線 斜体"
        )

    def test_quote_heading_and_list_markers_are_removed(self) -> None:
        self.assertEqual(
            normalize_text("> 引用\n# 見出し\n- 項目\n* 項目2\n1. 番号\n>>> 長い引用"),
            "引用、見出し、項目、項目2、番号、長い引用",
        )

    def test_repeated_characters_are_shortened_to_three(self) -> None:
        self.assertEqual(normalize_text("wwwwwwww"), "www")
        self.assertEqual(normalize_text("ははは"), "ははは")
        self.assertEqual(normalize_text("あああああ!!!!"), "あああ!!!")

    def test_newlines_and_spaces_are_collapsed(self) -> None:
        self.assertEqual(normalize_text("a  b\t\tc\n\nd　　e"), "a b c、d e")

    def test_empty_results(self) -> None:
        for text in ("", "   \n", "https://example.com", "||x||", "<@1>", "```a```"):
            with self.subTest(text=text):
                self.assertEqual(normalize_text(text), "")


class BuildSpeechTextTest(unittest.TestCase):
    def test_returns_the_body_only(self) -> None:
        self.assertEqual(build_speech_text("こんにちは", 200), "こんにちは")

    def test_body_is_truncated_without_announcing_it(self) -> None:
        self.assertEqual(build_speech_text("あいうえお", 3), "あいう")

    def test_empty_body_is_not_read(self) -> None:
        for content in ("", "https://example.com", "||secret||", "<@1> "):
            with self.subTest(content=content):
                self.assertIsNone(build_speech_text(content, 200))


class MentionsUserTest(unittest.TestCase):
    def test_only_the_exact_bot_mention_matches(self) -> None:
        self.assertTrue(mentions_user("<@42> hi", 42))
        self.assertTrue(mentions_user("hi <@!42>", 42))
        self.assertFalse(mentions_user("<@420> hi", 42))
        self.assertFalse(mentions_user("hi", 42))


class AssignAutoVoiceTest(unittest.TestCase):
    POOL = (3, 2, 8, 11)

    def test_same_user_gets_the_same_voice(self) -> None:
        # Fixed values: the hash must not change across runs or Python versions
        self.assertEqual(assign_auto_voice(1, self.POOL, {}), 2)
        self.assertEqual(assign_auto_voice(1, self.POOL, {}), 2)
        self.assertEqual(assign_auto_voice(123456789012345678, self.POOL, {}), 11)

    def test_default_voice_in_use_moves_to_the_next_in_rotation(self) -> None:
        self.assertEqual(assign_auto_voice(1, self.POOL, {2: 1}), 8)
        self.assertEqual(assign_auto_voice(1, self.POOL, {2: 1, 8: 1}), 11)

    def test_full_pool_picks_the_least_used_then_rotation_order(self) -> None:
        usage = {3: 2, 2: 2, 8: 2, 11: 1}
        self.assertEqual(assign_auto_voice(1, self.POOL, usage), 11)
        usage = {3: 1, 2: 1, 8: 2, 11: 2}
        # Rotation from 2 is 2, 8, 11, 3
        self.assertEqual(assign_auto_voice(1, self.POOL, usage), 2)

    def test_single_voice_pool(self) -> None:
        self.assertEqual(assign_auto_voice(1, (5,), {}), 5)
        self.assertEqual(assign_auto_voice(1, (5,), {5: 3}), 5)


class VoiceCatalogHelpersTest(unittest.TestCase):
    VOICES = (
        Voice(3, "ずんだもん", "ノーマル"),
        Voice(1, "ずんだもん", "あまあま"),
        Voice(2, "四国めたん", "ノーマル"),
        Voice(10, "Zundamon", "Normal"),
    )

    def test_label_and_credit(self) -> None:
        self.assertEqual(self.VOICES[0].label, "ずんだもん（ノーマル）")
        self.assertEqual(self.VOICES[0].credit, "VOICEVOX:ずんだもん")

    def test_resolve_by_id_or_exact_label(self) -> None:
        self.assertEqual(resolve_voice("3", self.VOICES), self.VOICES[0])
        self.assertEqual(resolve_voice("\uff13", self.VOICES), self.VOICES[0])
        self.assertEqual(
            resolve_voice("ずんだもん（あまあま）", self.VOICES), self.VOICES[1]
        )
        self.assertEqual(
            resolve_voice("ZUNDAMON（NORMAL）", self.VOICES),
            self.VOICES[3],
        )

    def test_resolve_rejects_unknown_and_partial_input(self) -> None:
        for query in ("", "99", "ずんだもん", "ずんだもん（"):
            with self.subTest(query=query):
                self.assertIsNone(resolve_voice(query, self.VOICES))

    def test_filter_matches_substrings_and_ids_in_catalog_order(self) -> None:
        self.assertEqual(filter_voices("ずんだ", self.VOICES), list(self.VOICES[:2]))
        self.assertEqual(filter_voices("ZUNDA", self.VOICES), [self.VOICES[3]])
        self.assertEqual(filter_voices("10", self.VOICES), [self.VOICES[3]])
        self.assertEqual(filter_voices("なし", self.VOICES), [])

    def test_filter_returns_at_most_25_and_all_for_empty_input(self) -> None:
        many = tuple(Voice(i, "キャラ", f"s{i}") for i in range(40))
        self.assertEqual(filter_voices("", many), list(many[:25]))
        self.assertEqual(filter_voices("キャラ", many), list(many[:25]))
        self.assertEqual(filter_voices("", ()), [])


class VoicevoxClientTest(unittest.TestCase):
    def client(self) -> VoicevoxClient:
        return VoicevoxClient("http://127.0.0.1:50021/")

    @mock.patch("ctfbot.features.tts.voicevox.requests.post")
    def test_query_then_synthesis(self, post: mock.Mock) -> None:
        post.side_effect = [
            mock.Mock(
                json=mock.Mock(return_value={"speedScale": 1.0, "pitchScale": 0.0})
            ),
            mock.Mock(content=b"RIFFxxxx"),
        ]
        self.assertEqual(self.client().synthesize("こんにちは", 3), b"RIFFxxxx")
        query_call, synthesis_call = post.call_args_list
        self.assertEqual(query_call.args, ("http://127.0.0.1:50021/audio_query",))
        self.assertEqual(
            query_call.kwargs["params"], {"text": "こんにちは", "speaker": 3}
        )
        self.assertEqual(query_call.kwargs["timeout"], (5, 30))
        self.assertEqual(synthesis_call.args, ("http://127.0.0.1:50021/synthesis",))
        self.assertEqual(synthesis_call.kwargs["params"], {"speaker": 3})
        self.assertEqual(
            synthesis_call.kwargs["json"], {"speedScale": 1.0, "pitchScale": 0.0}
        )
        self.assertEqual(synthesis_call.kwargs["timeout"], (5, 30))

    @mock.patch("ctfbot.features.tts.voicevox.requests.post")
    def test_failures_raise_external_api_error(self, post: mock.Mock) -> None:
        query_ok = mock.Mock(json=mock.Mock(return_value={}))
        invalid_json = mock.Mock(json=mock.Mock(side_effect=ValueError()))
        http_error = mock.Mock(
            raise_for_status=mock.Mock(side_effect=requests.HTTPError("422"))
        )
        cases = {
            "timeout": requests.Timeout(),
            "connection": requests.ConnectionError(),
            "invalid speaker": http_error,
            "invalid json": invalid_json,
            "query is not an object": mock.Mock(json=mock.Mock(return_value=[])),
        }
        for name, first in cases.items():
            with self.subTest(name=name):
                post.reset_mock()
                post.side_effect = [first]
                with self.assertRaises(ExternalAPIError):
                    self.client().synthesize("a", 3)
                post.assert_called_once()

        for name, second in {
            "synthesis http error": http_error,
            "not wav": mock.Mock(content=b"<html>"),
            "empty": mock.Mock(content=b""),
        }.items():
            with self.subTest(name=name):
                post.side_effect = [query_ok, second]
                with self.assertRaises(ExternalAPIError):
                    self.client().synthesize("a", 3)


class FetchVoicesTest(unittest.TestCase):
    def client(self) -> VoicevoxClient:
        return VoicevoxClient("http://127.0.0.1:50021/")

    def response(self, payload: object) -> mock.Mock:
        return mock.Mock(json=mock.Mock(return_value=payload))

    @mock.patch("ctfbot.features.tts.voicevox.requests.get")
    def test_talk_styles_are_kept_in_order_without_duplicates(
        self, get: mock.Mock
    ) -> None:
        get.return_value = self.response(
            [
                {
                    "name": "A",
                    "styles": [
                        {"id": 1, "name": "n", "type": "talk"},
                        {"id": 2, "name": "s", "type": "sing"},
                        {"id": 3, "name": "t", "type": "streaming_talk"},
                    ],
                },
                {
                    "name": "B",
                    "styles": [
                        {"id": 4, "name": "old"},
                        {"id": 1, "name": "dup", "type": "talk"},
                        {"id": 5, "name": "f", "type": "frame_decode"},
                        {"id": 6, "name": "g", "type": "singing_teacher"},
                    ],
                },
            ]
        )
        voices = self.client().fetch_voices()
        self.assertEqual(
            voices, (Voice(1, "A", "n"), Voice(3, "A", "t"), Voice(4, "B", "old"))
        )
        get.assert_called_once_with("http://127.0.0.1:50021/speakers", timeout=(3, 10))

    @mock.patch("ctfbot.features.tts.voicevox.requests.get")
    def test_failures_raise_external_api_error(self, get: mock.Mock) -> None:
        good_style = {"id": 1, "name": "n", "type": "talk"}
        cases: dict[str, object] = {
            "timeout": requests.Timeout(),
            "connection": requests.ConnectionError(),
            "http error": mock.Mock(
                raise_for_status=mock.Mock(side_effect=requests.HTTPError("500"))
            ),
            "invalid json": mock.Mock(json=mock.Mock(side_effect=ValueError())),
            "root is not a list": self.response({"name": "A"}),
            "no candidates": self.response([]),
            "only singing": self.response(
                [{"name": "A", "styles": [{"id": 1, "name": "n", "type": "sing"}]}]
            ),
            "name type": self.response([{"name": 1, "styles": [good_style]}]),
            "styles type": self.response([{"name": "A", "styles": "x"}]),
            "id type": self.response(
                [{"name": "A", "styles": [{"id": "1", "name": "n"}]}]
            ),
            "missing field": self.response([{"name": "A", "styles": [{"id": 1}]}]),
            "broken element is not skipped": self.response(
                [{"name": "A", "styles": [good_style, {"id": "x", "name": "n"}]}]
            ),
        }
        for name, outcome in cases.items():
            with self.subTest(name=name):
                get.reset_mock()
                if isinstance(outcome, Exception):
                    get.side_effect = outcome
                else:
                    get.side_effect = None
                    get.return_value = outcome
                with self.assertRaises(ExternalAPIError):
                    self.client().fetch_voices()
