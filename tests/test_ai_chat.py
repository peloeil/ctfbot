import asyncio
import datetime
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock
from zoneinfo import ZoneInfo

import discord
import requests

from ctfbot.errors import ExternalAPIError, RepositoryError
from ctfbot.features.ai_chat import (
    MAX_MONTHLY_REQUESTS,
    SYSTEM_PROMPT,
    AIChat,
    ChatCompletionClient,
    parse_prompt,
)
from ctfbot.helpers import MAX_MESSAGE_CONTENT_LENGTH
from ctfbot.runtime import BotRuntime


class PromptTest(unittest.TestCase):
    def test_only_direct_mentions_trigger_and_only_bot_mentions_are_removed(
        self,
    ) -> None:
        self.assertEqual(
            parse_prompt("<@42> こんにちは <@!42> <@13>", 42, None),
            "こんにちは  <@13>",
        )
        self.assertEqual(parse_prompt("<@!42> 質問", 42, None), "質問")
        self.assertEqual(parse_prompt("<@420> 質問", 42, None), None)
        self.assertEqual(parse_prompt("<@13> 質問", 42, None), None)
        self.assertEqual(parse_prompt("返信だけ", 42, None), None)

    def test_bot_managed_role_mention_triggers_and_other_roles_do_not(self) -> None:
        self.assertEqual(
            parse_prompt("<@&7> こんにちは <@&8>", 42, 7), "こんにちは <@&8>"
        )
        self.assertEqual(parse_prompt("<@&70> 質問", 42, 7), None)
        self.assertEqual(parse_prompt("<@&7> 質問", 42, None), None)


class ClientTest(unittest.TestCase):
    @mock.patch("ctfbot.features.ai_chat.requests.post")
    def test_request_contains_only_current_prompt(self, post: mock.Mock) -> None:
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": "回答"}}]
        }
        self.assertEqual(
            ChatCompletionClient(
                "secret", "https://example.test/v1/chat/completions", "model"
            ).complete("質問"),
            "回答",
        )
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args, ("https://example.test/v1/chat/completions",))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(kwargs["timeout"], (5, 180))
        self.assertEqual(
            set(kwargs["json"]),
            {
                "model",
                "messages",
                "reasoning_effort",
                "chat_template_kwargs",
                "stream",
            },
        )
        self.assertEqual(kwargs["json"]["reasoning_effort"], "high")
        self.assertEqual(
            kwargs["json"]["chat_template_kwargs"], {"enable_thinking": True}
        )
        self.assertEqual(
            kwargs["json"]["messages"],
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "質問"},
            ],
        )

    @mock.patch("ctfbot.features.ai_chat.requests.post")
    def test_failures_become_external_api_error_after_one_attempt(
        self, post: mock.Mock
    ) -> None:
        for response in (
            None,
            {},
            {"choices": []},
            {"choices": [{"message": {"content": ""}}]},
        ):
            with self.subTest(response=response):
                post.reset_mock()
                post.return_value.raise_for_status.side_effect = None
                post.return_value.json.side_effect = (
                    ValueError() if response is None else None
                )
                post.return_value.json.return_value = response
                with self.assertRaises(ExternalAPIError):
                    ChatCompletionClient(
                        "secret", "https://example.test/v1/chat/completions", "model"
                    ).complete("質問")
                post.assert_called_once()

        for error in (
            requests.Timeout(),
            requests.HTTPError("429"),
            requests.HTTPError("500"),
        ):
            with self.subTest(error=error):
                post.reset_mock()
                post.return_value.raise_for_status.side_effect = error
                with self.assertRaises(ExternalAPIError):
                    ChatCompletionClient(
                        "secret", "https://example.test/v1/chat/completions", "model"
                    ).complete("質問")
                post.assert_called_once()


class ChatTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot = mock.Mock()
        self.bot.user.id = 42
        self.tzinfo = datetime.timezone(datetime.timedelta(hours=9))
        self.db = mock.Mock()
        self.db.count_ai_chat_requests.return_value = 0
        self.bot.runtime = self._runtime(api_key="secret")
        self.bot.get_context = mock.AsyncMock(
            return_value=SimpleNamespace(command=None)
        )
        self.chat = AIChat(cast(Any, self.bot))
        self.message = self._message()

    def _runtime(self, api_key: str | None) -> BotRuntime:
        return BotRuntime(
            settings=cast(
                Any,
                SimpleNamespace(
                    guild_id=99,
                    tzinfo=self.tzinfo,
                    ai_chat_api_key=api_key,
                    ai_chat_api_url="https://example.test/v1/chat/completions",
                    ai_chat_model="model",
                ),
            ),
            db=self.db,
        )

    @staticmethod
    def _message(
        *,
        content: str = "<@42> 質問",
        author_id: int = 123,
        guild_id: int | None = 99,
        is_bot: bool = False,
        webhook_id: int | None = None,
        message_type: discord.MessageType = discord.MessageType.default,
    ) -> mock.Mock:
        message = mock.Mock()
        if guild_id is None:
            message.guild = None
        else:
            message.guild.id = guild_id
            message.guild.self_role = None
        message.author.bot = is_bot
        message.author.id = author_id
        message.webhook_id = webhook_id
        message.type = message_type
        message.content = content
        message.id = 5
        message.reply = mock.AsyncMock()
        message.channel = mock.MagicMock()
        return message

    def _answer_with(self, answer: str = "回答") -> mock.Mock:
        self.chat.client = mock.Mock()
        self.chat.client.complete.return_value = answer
        return self.chat.client

    async def _hold_api_until_released(self) -> tuple[asyncio.Semaphore, mock.Mock]:
        """Block the API until cleanup; the semaphore counts started calls."""
        started = asyncio.Semaphore(0)
        release = asyncio.Event()
        loop = asyncio.get_running_loop()

        def complete(prompt: str) -> str:
            loop.call_soon_threadsafe(started.release)
            asyncio.run_coroutine_threadsafe(release.wait(), loop).result()
            return prompt

        # Without this a failing assertion leaves the worker thread blocked forever.
        self.addCleanup(release.set)
        client = mock.Mock()
        client.complete.side_effect = complete
        self.chat.client = client
        return started, client

    async def test_typing_is_shown_only_while_waiting_for_the_api(self) -> None:
        typing = self.message.channel.typing.return_value

        def complete(prompt: str) -> str:
            typing.__aenter__.assert_awaited_once()
            typing.__aexit__.assert_not_awaited()
            return "回答"

        self.chat.client = mock.Mock()
        self.chat.client.complete.side_effect = complete
        await self.chat.on_message(cast(Any, self.message))
        self.chat.client.complete.assert_called_once()
        typing.__aexit__.assert_awaited_once()
        self.message.reply.assert_awaited_once()

    async def test_only_message_content_is_sent_to_the_api(self) -> None:
        client = self._answer_with()
        self.message.reference = mock.Mock()
        self.message.attachments = [mock.Mock()]
        self.message.embeds = [mock.Mock()]
        await self.chat.on_message(cast(Any, self.message))
        client.complete.assert_called_once_with("質問")
        self.message.channel.history.assert_not_called()
        self.message.channel.fetch_message.assert_not_called()

    async def test_reply_does_not_ping_anyone(self) -> None:
        self._answer_with()
        await self.chat.on_message(cast(Any, self.message))
        args, kwargs = self.message.reply.await_args
        self.assertEqual(args, ("回答",))
        self.assertEqual(
            kwargs["allowed_mentions"].to_dict(),
            discord.AllowedMentions.none().to_dict(),
        )
        self.assertFalse(kwargs["mention_author"])

    async def test_answered_request_is_recorded_for_the_author(self) -> None:
        self._answer_with()
        await self.chat.on_message(cast(Any, self.message))
        self.db.record_ai_chat_request.assert_called_once_with(123, mock.ANY)

    async def test_usage_period_is_the_month_in_the_configured_timezone(self) -> None:
        self._answer_with()
        now = datetime.datetime(2026, 10, 31, 23, 30, tzinfo=datetime.UTC)
        for tzinfo, period in (
            (self.tzinfo, "2026-11"),
            (ZoneInfo("America/Los_Angeles"), "2026-10"),
        ):
            with self.subTest(tzinfo=tzinfo):
                self.db.record_ai_chat_request.reset_mock()
                cast(Any, self.chat).tzinfo = tzinfo
                with mock.patch("ctfbot.features.ai_chat.datetime") as clock:
                    clock.datetime.now.side_effect = now.astimezone
                    await self.chat.on_message(cast(Any, self._message()))
                self.db.record_ai_chat_request.assert_called_once_with(123, period)

    async def test_bot_managed_role_mention_is_answered(self) -> None:
        client = self._answer_with()
        self.message.guild.self_role = SimpleNamespace(id=7)
        self.message.content = "<@&7> 質問"
        await self.chat.on_message(cast(Any, self.message))
        client.complete.assert_called_once_with("質問")
        self.message.reply.assert_awaited_once()

    async def test_ignored_messages(self) -> None:
        variants: tuple[dict[str, Any], ...] = (
            {"guild_id": None},
            {"guild_id": 100},
            {"is_bot": True},
            {"webhook_id": 4},
            {"message_type": discord.MessageType.pins_add},
            {"content": "返信 ping だけ"},
        )
        client = self._answer_with()
        for changes in variants:
            with self.subTest(changes=changes):
                message = self._message(**changes)
                await self.chat.on_message(cast(Any, message))
                message.reply.assert_not_awaited()
        client.complete.assert_not_called()

    async def test_command_invocation_is_not_answered(self) -> None:
        client = self._answer_with()
        self.bot.get_context.return_value.command = mock.Mock()
        await self.chat.on_message(cast(Any, self.message))
        self.message.reply.assert_not_awaited()
        client.complete.assert_not_called()

    async def test_missing_token_disables_listener(self) -> None:
        self.bot.runtime = self._runtime(api_key=None)
        disabled = AIChat(cast(Any, self.bot))
        await disabled.on_message(cast(Any, self.message))
        self.message.reply.assert_not_awaited()
        self.bot.get_context.assert_not_awaited()

    async def test_mention_without_question_asks_for_one(self) -> None:
        client = self._answer_with()
        self.message.content = "<@42>"
        await self.chat.on_message(cast(Any, self.message))
        self.assertEqual(
            self.message.reply.await_args.args[0],
            "メンションに続けて質問を書いてください。",
        )
        client.complete.assert_not_called()

    async def test_question_over_2000_characters_is_rejected(self) -> None:
        client = self._answer_with()
        self.message.content = "<@42>" + "a" * 2001
        await self.chat.on_message(cast(Any, self.message))
        self.assertEqual(
            self.message.reply.await_args.args[0],
            "質問は 2000 文字以内にしてください。",
        )
        client.complete.assert_not_called()

    async def test_question_of_exactly_2000_characters_is_answered(self) -> None:
        client = self._answer_with()
        self.message.content = "<@42>" + "a" * 2000
        await self.chat.on_message(cast(Any, self.message))
        client.complete.assert_called_once_with("a" * 2000)

    async def test_second_request_from_user_being_answered_is_rejected(self) -> None:
        started, client = await self._hold_api_until_released()
        first = asyncio.create_task(self.chat.on_message(cast(Any, self.message)))
        await started.acquire()
        second = self._message(content="<@42> もう一度")
        await self.chat.on_message(cast(Any, second))
        self.assertIn("回答中", second.reply.await_args.args[0])
        client.complete.assert_called_once()
        first.cancel()

    async def test_request_is_rejected_while_two_users_are_being_answered(
        self,
    ) -> None:
        started, client = await self._hold_api_until_released()
        running = [
            asyncio.create_task(
                self.chat.on_message(cast(Any, self._message(author_id=user_id)))
            )
            for user_id in (1, 2)
        ]
        await started.acquire()
        await started.acquire()
        third = self._message(author_id=3)
        await self.chat.on_message(cast(Any, third))
        self.assertIn("混雑", third.reply.await_args.args[0])
        self.assertEqual(client.complete.call_count, 2)
        for task in running:
            task.cancel()
        self.db.record_ai_chat_request.assert_not_called()

    async def test_user_at_the_monthly_limit_is_told_without_calling_the_api(
        self,
    ) -> None:
        client = self._answer_with()
        self.db.count_ai_chat_requests.return_value = MAX_MONTHLY_REQUESTS
        await self.chat.on_message(cast(Any, self.message))
        client.complete.assert_not_called()
        self.db.record_ai_chat_request.assert_not_called()
        self.assertEqual(
            self.message.reply.await_args.args[0],
            "今月の利用上限（30 回）に達しました。翌月にリセットされます。",
        )

    async def test_user_one_below_the_monthly_limit_is_answered(self) -> None:
        self._answer_with()
        self.db.count_ai_chat_requests.return_value = MAX_MONTHLY_REQUESTS - 1
        await self.chat.on_message(cast(Any, self.message))
        self.assertEqual(self.message.reply.await_args.args[0], "回答")

    async def test_failure_does_not_record_usage(self) -> None:
        self.chat.client = mock.Mock()
        self.chat.client.complete.side_effect = ExternalAPIError("failed")
        with self.assertLogs("ctfbot", level="WARNING"):
            await self.chat.on_message(cast(Any, self.message))
        self.db.record_ai_chat_request.assert_not_called()

    async def test_api_failure_is_reported_and_next_request_is_accepted(self) -> None:
        client = self._answer_with()
        client.complete.side_effect = [ExternalAPIError("failed"), "回答"]
        with self.assertLogs("ctfbot", level="WARNING"):
            await self.chat.on_message(cast(Any, self.message))
        self.assertEqual(
            self.message.reply.await_args.args[0], "AI の応答を取得できませんでした。"
        )
        await self.chat.on_message(cast(Any, self.message))
        self.assertEqual(self.message.reply.await_args.args[0], "回答")

    async def test_next_request_is_accepted_after_the_message_was_deleted(
        self,
    ) -> None:
        client = self._answer_with()
        self.message.reply.side_effect = discord.NotFound(
            mock.Mock(status=404, reason="Not Found"), "deleted"
        )
        with self.assertLogs("ctfbot", level="ERROR"):
            await self.chat.on_message(cast(Any, self.message))
        self.message.reply.side_effect = None
        await self.chat.on_message(cast(Any, self.message))
        self.assertEqual(client.complete.call_count, 2)
        self.assertEqual(self.message.reply.await_args.args[0], "回答")

    async def test_long_answer_is_truncated_to_fit_a_discord_message(self) -> None:
        self._answer_with("x" * 2100)
        await self.chat.on_message(cast(Any, self.message))
        reply = self.message.reply.await_args.args[0]
        self.assertEqual(len(reply), MAX_MESSAGE_CONTENT_LENGTH)
        self.assertTrue(reply.endswith("..."))

    async def test_answer_is_sent_even_if_recording_usage_fails(self) -> None:
        self._answer_with()
        self.db.record_ai_chat_request.side_effect = RepositoryError("db down")
        with self.assertLogs("ctfbot", level="ERROR"):
            await self.chat.on_message(cast(Any, self.message))
        self.assertEqual(self.message.reply.await_args.args[0], "回答")

    async def test_answered_request_is_logged_without_prompt_text(self) -> None:
        self._answer_with()
        with self.assertLogs("ctfbot", level="INFO") as logs:
            await self.chat.on_message(cast(Any, self.message))
        output = "\n".join(logs.output)
        self.assertIn("AI chat answered", output)
        self.assertIn("message_id=5", output)
        self.assertNotIn("質問", output)
