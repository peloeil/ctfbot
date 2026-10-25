import asyncio
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import discord
import requests

from ctfbot.errors import ExternalAPIError
from ctfbot.features.ai_chat import AIChat, ChatCompletionClient, parse_prompt
from ctfbot.runtime import BotRuntime


class PromptTest(unittest.TestCase):
    def test_only_direct_mentions_trigger_and_only_bot_mentions_are_removed(
        self,
    ) -> None:
        self.assertEqual(
            parse_prompt("<@42> こんにちは <@!42> <@13>", 42), "こんにちは  <@13>"
        )
        self.assertEqual(parse_prompt("<@!42> 質問", 42), "質問")
        self.assertEqual(parse_prompt("<@420> 質問", 42), None)
        self.assertEqual(parse_prompt("<@13> 質問", 42), None)
        self.assertEqual(parse_prompt("返信だけ", 42), None)


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
        self.assertEqual(kwargs["timeout"], (5, 60))
        self.assertEqual(
            set(kwargs["json"]), {"model", "messages", "max_tokens", "stream"}
        )
        self.assertEqual(
            kwargs["json"]["messages"][1], {"role": "user", "content": "質問"}
        )

    @mock.patch("ctfbot.features.ai_chat.requests.post")
    def test_errors_do_not_retry(self, post: mock.Mock) -> None:
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
        self.bot.runtime = BotRuntime(
            settings=cast(
                Any,
                SimpleNamespace(
                    guild_id=99,
                    ai_chat_api_key="secret",
                    ai_chat_api_url="https://example.test/v1/chat/completions",
                    ai_chat_model="model",
                ),
            ),
            db=mock.Mock(),
        )
        self.bot.get_context = mock.AsyncMock(
            return_value=SimpleNamespace(command=None)
        )
        self.chat = AIChat(cast(Any, self.bot))
        self.message = mock.Mock()
        self.message.guild.id = 99
        self.message.author.bot = False
        self.message.author.id = 123
        self.message.webhook_id = None
        self.message.type = discord.MessageType.default
        self.message.content = "<@42> 質問"
        self.message.id = 5
        self.message.reply = mock.AsyncMock()

    async def test_reply_uses_only_message_content_and_does_not_ping(self) -> None:
        self.chat.client = mock.Mock()
        self.chat.client.complete.return_value = "回答"
        self.message.reference = mock.Mock()
        self.message.attachments = [mock.Mock()]
        self.message.embeds = [mock.Mock()]
        await self.chat.on_message(cast(Any, self.message))
        self.chat.client.complete.assert_called_once_with("質問")
        args, kwargs = self.message.reply.await_args
        self.assertEqual(args, ("回答",))
        self.assertEqual(
            kwargs["allowed_mentions"].to_dict(),
            discord.AllowedMentions.none().to_dict(),
        )
        self.assertFalse(kwargs["mention_author"])
        self.message.channel.history.assert_not_called()
        self.message.channel.fetch_message.assert_not_called()
        self.assertEqual(self.chat.active_users, set())

    async def test_ignored_messages(self) -> None:
        variants = (
            {"guild": None},
            {"guild.id": 100},
            {"author.bot": True},
            {"webhook_id": 4},
            {"type": discord.MessageType.pins_add},
            {"content": "返信 ping だけ"},
        )
        for changes in variants:
            with self.subTest(changes=changes):
                message = mock.Mock()
                message.guild.id = 99
                message.author.bot = False
                message.webhook_id = None
                message.type = discord.MessageType.default
                message.content = "<@42> 質問"
                message.reply = mock.AsyncMock()
                for key, value in changes.items():
                    target = message
                    parts = key.split(".")
                    for part in parts[:-1]:
                        target = getattr(target, part)
                    setattr(target, parts[-1], value)
                await self.chat.on_message(cast(Any, message))
                message.reply.assert_not_awaited()
        self.bot.get_context.return_value.command = mock.Mock()
        await self.chat.on_message(cast(Any, self.message))
        self.message.reply.assert_not_awaited()

    async def test_missing_token_disables_listener(self) -> None:
        self.bot.runtime = BotRuntime(
            settings=cast(
                Any,
                SimpleNamespace(
                    guild_id=99,
                    ai_chat_api_key=None,
                    ai_chat_api_url="https://example.test/v1/chat/completions",
                    ai_chat_model="model",
                ),
            ),
            db=mock.Mock(),
        )
        disabled = AIChat(cast(Any, self.bot))
        await disabled.on_message(cast(Any, self.message))
        self.message.reply.assert_not_awaited()
        self.bot.get_context.assert_not_awaited()

    async def test_invalid_and_busy_requests_do_not_call_api(self) -> None:
        self.chat.client = mock.Mock()
        for content, expected in (
            ("<@42>", "メンションに続けて質問を書いてください。"),
            ("<@42>" + "a" * 2001, "質問は 2000 文字以内にしてください。"),
        ):
            self.message.content = content
            await self.chat.on_message(cast(Any, self.message))
            self.assertEqual(self.message.reply.await_args.args[0], expected)
        self.chat.client.complete.assert_not_called()
        self.message.content = "<@42> 質問"
        self.chat.active_users.add(123)
        await self.chat.on_message(cast(Any, self.message))
        self.assertIn("回答中", self.message.reply.await_args.args[0])
        self.chat.active_users = {1, 2}
        await self.chat.on_message(cast(Any, self.message))
        self.assertIn("混雑", self.message.reply.await_args.args[0])

    async def test_failure_and_deleted_message_release_slot(self) -> None:
        self.chat.client = mock.Mock()
        self.chat.client.complete.side_effect = ExternalAPIError("failed")
        await self.chat.on_message(cast(Any, self.message))
        self.assertEqual(
            self.message.reply.await_args.args[0], "AI の応答を取得できませんでした。"
        )
        self.assertEqual(self.chat.active_users, set())
        self.chat.client.complete.side_effect = None
        self.chat.client.complete.return_value = "x" * 2100
        self.message.reply.side_effect = discord.NotFound(
            mock.Mock(status=404, reason="Not Found"), "deleted"
        )
        await self.chat.on_message(cast(Any, self.message))
        self.assertEqual(len(self.message.reply.await_args.args[0]), 1900)
        self.assertEqual(self.chat.active_users, set())

    async def test_concurrent_requests_are_rejected(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        def complete(prompt: str) -> str:
            loop.call_soon_threadsafe(started.set)
            asyncio.run_coroutine_threadsafe(release.wait(), loop).result()
            return prompt

        loop = asyncio.get_running_loop()
        self.chat.client = mock.Mock()
        self.chat.client.complete.side_effect = complete
        first = asyncio.create_task(self.chat.on_message(cast(Any, self.message)))
        await started.wait()
        second = mock.Mock()
        second.guild.id = 99
        second.author.bot = False
        second.author.id = 123
        second.webhook_id = None
        second.type = discord.MessageType.default
        second.content = "<@42> もう一度"
        second.reply = mock.AsyncMock()
        await self.chat.on_message(cast(Any, second))
        second.reply.assert_awaited_once()
        self.assertIn("回答中", second.reply.await_args_list[0].args[0])
        release.set()
        await first
