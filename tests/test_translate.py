import asyncio
import unittest
from typing import Any, cast
from unittest import mock

import discord
import requests

from ctfbot.errors import ExternalAPIError, ServiceError
from ctfbot.features.translate import (
    TranslateCommands,
    TranslationClient,
    build_prompt,
    choose_languages,
    validate_text,
)


class PromptTest(unittest.TestCase):
    def test_auto_target_depends_on_kana(self) -> None:
        self.assertEqual(choose_languages("こんにちは", None), ("en", "ja"))
        self.assertEqual(choose_languages("カタカナ", None), ("en", "ja"))
        self.assertEqual(choose_languages("Hello", None), ("ja", None))
        self.assertEqual(choose_languages("你好", None), ("ja", None))

    def test_text_with_kana_forced_to_japanese_leaves_source_to_model(self) -> None:
        self.assertEqual(choose_languages("Use the フラグ format", "ja"), ("ja", None))
        self.assertEqual(choose_languages("こんにちは", "en"), ("en", "ja"))

    def test_builds_pfml3_prompt_with_optional_source(self) -> None:
        self.assertEqual(
            build_prompt("こんにちは", "en", "ja"),
            "<|plamo:tag|>dataset<|plamo:msg|>translation"
            "<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>ja"
            "<|plamo:msg|>こんにちは"
            "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>en<|plamo:msg|>",
        )
        self.assertEqual(
            build_prompt("Hello", "ja"),
            "<|plamo:tag|>dataset<|plamo:msg|>translation"
            "<|plamo:tag|>input<|plamo:msg|>Hello"
            "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja<|plamo:msg|>",
        )


class ValidateTextTest(unittest.TestCase):
    def test_strips_surrounding_whitespace(self) -> None:
        self.assertEqual(validate_text("  hello  ", 10), "hello")

    def test_rejects_empty_and_over_limit(self) -> None:
        for text in ("", "   "):
            with self.subTest(text=text), self.assertRaises(ServiceError):
                validate_text(text, 10)
        with self.assertRaises(ServiceError):
            validate_text("a" * 11, 10)

    def test_rejects_pfml3_control_tokens(self) -> None:
        with self.assertRaises(ServiceError):
            validate_text("<|plamo:tag|>", 100)


class ClientTest(unittest.TestCase):
    @mock.patch("ctfbot.features.translate.requests.get")
    def test_check_ready_uses_health_endpoint(self, get: mock.Mock) -> None:
        TranslationClient("http://127.0.0.1:8080/", "model").check_ready()

        get.assert_called_once()
        args, kwargs = get.call_args
        self.assertEqual(args, ("http://127.0.0.1:8080/health",))
        self.assertEqual(kwargs["timeout"], (1, 2))

    @mock.patch("ctfbot.features.translate.requests.post")
    def test_translate_builds_prompt_and_parses_text(self, post: mock.Mock) -> None:
        post.return_value.json.return_value = {"choices": [{"text": " 回答 "}]}

        result = TranslationClient("http://127.0.0.1:8080/", "plamo").translate(
            "質問", "en", "ja"
        )

        self.assertEqual(result, "回答")
        args, kwargs = post.call_args
        self.assertEqual(args, ("http://127.0.0.1:8080/v1/completions",))
        self.assertEqual(kwargs["timeout"], (5, 120))
        self.assertEqual(kwargs["json"]["model"], "plamo")
        self.assertEqual(kwargs["json"]["temperature"], 0)
        self.assertEqual(kwargs["json"]["prompt"], build_prompt("質問", "en", "ja"))
        self.assertEqual(kwargs["json"]["stop"], ["<|plamo:tag|>", "<|plamo:bos|>"])

    @mock.patch("ctfbot.features.translate.requests.post")
    def test_failures_become_external_api_error_after_one_attempt(
        self, post: mock.Mock
    ) -> None:
        for response in (
            None,
            {},
            {"choices": []},
            {"choices": [{"text": ""}]},
        ):
            with self.subTest(response=response):
                post.reset_mock()
                post.return_value.raise_for_status.side_effect = None
                post.return_value.json.side_effect = (
                    ValueError() if response is None else None
                )
                post.return_value.json.return_value = response
                with self.assertRaises(ExternalAPIError):
                    TranslationClient("http://127.0.0.1:8080", "m").translate(
                        "質問", "en"
                    )
                post.assert_called_once()

        for error in (requests.Timeout(), requests.HTTPError("500")):
            with self.subTest(error=error):
                post.reset_mock()
                post.return_value.raise_for_status.side_effect = error
                with self.assertRaises(ExternalAPIError):
                    TranslationClient("http://127.0.0.1:8080", "m").translate(
                        "質問", "en"
                    )
                post.assert_called_once()


class CogTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = mock.Mock()
        self.client = mock.Mock()
        self.engine = mock.Mock()
        self.engine.call = mock.AsyncMock()
        self.engine.shutdown = mock.AsyncMock()
        self.cog = TranslateCommands(self.bot, self.client, self.engine, 100)
        self.bot.tree = mock.Mock()
        self.interaction = mock.Mock(spec=discord.Interaction)
        self.interaction.user = mock.Mock()
        self.interaction.user.id = 1
        self.interaction.user.name = "user"
        self.interaction.channel = mock.Mock()
        self.interaction.channel.id = 2
        self.interaction.channel.name = "general"
        self.interaction.channel_id = 2
        self.interaction.response = mock.Mock()
        self.interaction.response.is_done.return_value = False
        self.interaction.followup = mock.Mock()
        self.interaction.followup.send = mock.AsyncMock()
        self.interaction.response.send_message = mock.AsyncMock()

        async def defer(**_: Any) -> None:
            self.interaction.response.is_done.return_value = True

        self.interaction.response.defer = mock.AsyncMock(side_effect=defer)

    async def _translate(self, text: str, target: str = "auto") -> None:
        callback = cast(Any, self.cog.translate_text.callback)
        await callback(self.cog, self.interaction, text, target)

    async def test_translates_to_english_for_japanese_and_is_ephemeral(self) -> None:
        self.engine.call.return_value = "translated"

        await self._translate("こんにちは")

        self.engine.call.assert_awaited_once_with(
            self.client.translate, "こんにちは", "en", "ja"
        )
        args, kwargs = self.interaction.followup.send.await_args
        self.assertEqual(args[0], "translated")
        self.assertTrue(kwargs["ephemeral"])

    async def test_request_is_deferred_as_ephemeral_thinking(self) -> None:
        self.engine.call.return_value = "translated"

        await self._translate("hello")

        self.interaction.response.defer.assert_awaited_once_with(
            ephemeral=True, thinking=True
        )

    async def test_auto_target_is_detected_from_text(self) -> None:
        self.engine.call.return_value = "translated"

        await self._translate("Hello", "auto")

        self.engine.call.assert_awaited_once_with(
            self.client.translate, "Hello", "ja", None
        )

    async def test_explicit_target_overrides_detection(self) -> None:
        self.engine.call.return_value = "translated"

        await self._translate("こんにちは", "ja")

        self.engine.call.assert_awaited_once_with(
            self.client.translate, "こんにちは", "ja", None
        )

    async def test_text_over_limit_to_english_is_rejected(self) -> None:
        self.cog.max_chars = 2000

        await self._translate("あ" * 601)

        self.engine.call.assert_not_awaited()
        args, _ = self.interaction.response.send_message.await_args
        self.assertEqual(args[0], "翻訳できるのは 600 文字までです。")

    async def test_limit_is_higher_when_translating_to_japanese(self) -> None:
        self.cog.max_chars = 2000
        self.engine.call.return_value = "translated"

        await self._translate("a" * 2000)

        self.engine.call.assert_awaited_once()

    async def test_validation_failure_does_not_defer(self) -> None:
        await self._translate("   ")

        self.interaction.response.defer.assert_not_awaited()
        self.engine.call.assert_not_awaited()
        args, kwargs = self.interaction.response.send_message.await_args
        self.assertEqual(args[0], "翻訳するテキストを指定してください。")
        self.assertTrue(kwargs["ephemeral"])

    async def test_engine_failure_is_reported_once_without_retry(self) -> None:
        self.engine.call.side_effect = ExternalAPIError("down")

        with self.assertLogs("ctfbot", "WARNING"):
            await self._translate("hello")

        self.engine.call.assert_awaited_once()
        args, _ = self.interaction.followup.send.await_args
        self.assertEqual(args[0], "翻訳結果を取得できませんでした。")

    async def test_unexpected_error_is_reported_and_next_request_is_accepted(
        self,
    ) -> None:
        self.engine.call.side_effect = [RuntimeError("boom"), "translated"]

        with self.assertLogs("ctfbot", "ERROR"):
            await self._translate("hello")
        args, _ = self.interaction.followup.send.await_args
        self.assertEqual(args[0], "翻訳中にエラーが発生しました。")

        await self._translate("hello")
        args, _ = self.interaction.followup.send.await_args
        self.assertEqual(args[0], "translated")

    async def test_requests_waiting_on_defer_count_toward_the_limit(self) -> None:
        gate = asyncio.Event()

        async def slow_defer(**_: Any) -> None:
            await gate.wait()
            self.interaction.response.is_done.return_value = True

        self.interaction.response.defer.side_effect = slow_defer
        self.engine.call.return_value = "translated"
        pending = [asyncio.create_task(self._translate("hello")) for _ in range(2)]
        await asyncio.sleep(0)

        await self._translate("hello")

        args, _ = self.interaction.response.send_message.await_args
        self.assertIn("混雑", args[0])
        gate.set()
        await asyncio.gather(*pending)
        self.assertEqual(self.engine.call.await_count, 2)

        await self._translate("hello")
        self.assertEqual(self.engine.call.await_count, 3)

    async def test_truncates_long_translation(self) -> None:
        self.engine.call.return_value = "a" * 2000

        await self._translate("hello")

        args, _ = self.interaction.followup.send.await_args
        self.assertEqual(len(args[0]), 1900)
        self.assertTrue(args[0].endswith("..."))

    async def test_cog_load_and_unload_manage_menu_and_engine(self) -> None:
        await self.cog.cog_load()
        self.bot.tree.add_command.assert_called_once_with(self.cog.context_menu)
        self.engine.start_idle_watch.assert_called_once()

        await self.cog.cog_unload()
        self.bot.tree.remove_command.assert_called_once_with(
            "メッセージを翻訳", type=discord.AppCommandType.message
        )
        self.engine.shutdown.assert_awaited_once()

    async def test_context_menu_rejects_message_without_text(self) -> None:
        message = mock.Mock(spec=discord.Message)
        message.content = " "

        await self.cog.translate_message(self.interaction, message)

        self.interaction.response.defer.assert_not_awaited()
        args, _ = self.interaction.response.send_message.await_args
        self.assertEqual(args[0], "本文のあるメッセージを対象にしてください。")


if __name__ == "__main__":
    unittest.main()
