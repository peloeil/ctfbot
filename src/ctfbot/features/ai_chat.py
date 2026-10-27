import asyncio
import datetime
import re

import discord
import requests
from discord.ext import commands

from ctfbot.errors import ExternalAPIError, RepositoryError
from ctfbot.helpers import MAX_MESSAGE_CONTENT_LENGTH
from ctfbot.log import logger
from ctfbot.runtime import get_runtime

SYSTEM_PROMPT = "日本語で簡潔に答えてください。回答は 1500 文字以内にしてください。"
MAX_PROMPT_LENGTH = 2000
MAX_CONCURRENT_REQUESTS = 2
MAX_MONTHLY_REQUESTS = 30


def parse_prompt(content: str, bot_id: int, role_id: int | None) -> str | None:
    pattern = rf"<@!?{bot_id}>"
    if role_id is not None:
        pattern += rf"|<@&{role_id}>"
    mention = re.compile(pattern)
    if not mention.search(content):
        return None
    return mention.sub("", content).strip()


class ChatCompletionClient:
    def __init__(self, api_key: str, api_url: str, model: str) -> None:
        self.api_key = api_key
        self.api_url = api_url
        self.model = model

    def complete(self, prompt: str) -> str:
        try:
            response = requests.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    # Not reasoning_effort alone: Gemma 4 ignores it and only
                    # thinks when enable_thinking is set.
                    # No max_tokens: reasoning tokens count against it and can
                    # leave content empty, and the reply is truncated to fit
                    # Discord anyway.
                    "reasoning_effort": "high",
                    "chat_template_kwargs": {"enable_thinking": True},
                    "stream": False,
                },
                timeout=(5, 180),
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ExternalAPIError("Chat completion request failed.") from exc

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExternalAPIError("Unexpected chat completion response.") from exc
        if not isinstance(content, str) or not content.strip():
            raise ExternalAPIError("Empty chat completion response.")
        return content


class AIChat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        runtime = get_runtime(bot)
        settings = runtime.settings
        self.bot = bot
        self.db = runtime.db
        self.tzinfo = settings.tzinfo
        self.guild_id = settings.guild_id
        self.client = (
            ChatCompletionClient(
                settings.ai_chat_api_key,
                settings.ai_chat_api_url,
                settings.ai_chat_model,
            )
            if settings.ai_chat_api_key is not None
            else None
        )
        self.active_users: set[int] = set()
        if self.client is None:
            logger.info("AI chat disabled (no API key configured)")

    async def _reply(self, message: discord.Message, text: str) -> None:
        try:
            await message.reply(
                text,
                allowed_mentions=discord.AllowedMentions.none(),
                mention_author=False,
            )
        except discord.HTTPException:
            logger.exception("Failed to reply to AI chat message id=%s", message.id)

    def _current_period(self) -> str:
        return datetime.datetime.now(self.tzinfo).strftime("%Y-%m")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if (
            self.client is None
            or message.guild is None
            or message.guild.id != self.guild_id
            or message.author.bot
            or message.webhook_id is not None
            or message.type
            not in (discord.MessageType.default, discord.MessageType.reply)
            or self.bot.user is None
        ):
            return
        role = message.guild.self_role
        prompt = parse_prompt(
            message.content, self.bot.user.id, role.id if role is not None else None
        )
        if prompt is None:
            return
        try:
            context = await self.bot.get_context(message)
            if context.command is not None:
                return
            if not prompt:
                await self._reply(message, "メンションに続けて質問を書いてください。")
                return
            if len(prompt) > MAX_PROMPT_LENGTH:
                await self._reply(message, "質問は 2000 文字以内にしてください。")
                return
            if message.author.id in self.active_users:
                await self._reply(message, "前の質問に回答中です。")
                return
            if len(self.active_users) >= MAX_CONCURRENT_REQUESTS:
                await self._reply(
                    message, "現在混雑しています。しばらくしてから再度お試しください。"
                )
                return
            period = self._current_period()
            used = await asyncio.to_thread(
                self.db.count_ai_chat_requests, message.author.id, period
            )
            if used >= MAX_MONTHLY_REQUESTS:
                await self._reply(
                    message,
                    f"今月の利用上限（{MAX_MONTHLY_REQUESTS} 回）に達しました。"
                    "翌月にリセットされます。",
                )
                return

            self.active_users.add(message.author.id)
            try:
                try:
                    async with message.channel.typing():
                        answer = await asyncio.to_thread(self.client.complete, prompt)
                except ExternalAPIError:
                    logger.warning(
                        "AI chat request failed for message id=%s", message.id
                    )
                    await self._reply(message, "AI の応答を取得できませんでした。")
                else:
                    try:
                        await asyncio.to_thread(
                            self.db.record_ai_chat_request, message.author.id, period
                        )
                    except RepositoryError:
                        logger.exception(
                            "Failed to record AI chat usage for message id=%s",
                            message.id,
                        )
                    if len(answer) > MAX_MESSAGE_CONTENT_LENGTH:
                        answer = answer[: MAX_MESSAGE_CONTENT_LENGTH - 3] + "..."
                    await self._reply(message, answer)
            finally:
                self.active_users.remove(message.author.id)
        except Exception:
            logger.exception("Unexpected AI chat error for message id=%s", message.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AIChat(bot))
