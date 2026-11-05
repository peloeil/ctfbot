import re

import discord
import requests
from discord import app_commands
from discord.ext import commands

from ctfbot.errors import ExternalAPIError, ServiceError
from ctfbot.helpers import (
    MAX_MESSAGE_CONTENT_LENGTH,
    format_log_channel,
    format_log_user,
    send_interaction,
)
from ctfbot.log import logger
from ctfbot.podman import PodmanEngine
from ctfbot.runtime import get_runtime

MAX_CONCURRENT_REQUESTS = 2
# English runs 2-3x the characters of Japanese, so a longer input would not fit
# in one Discord message after translation.
MAX_CHARS_TO_ENGLISH = 600
TRANSLATE_TIMEOUT_SECONDS = 120
MAX_NEW_TOKENS = 2048
STOP_TOKENS = ("<|plamo:tag|>", "<|plamo:bos|>")
READY_TIMEOUT_SECONDS = 60.0
_KANA = re.compile(r"[\u3040-\u30ff]")


def choose_languages(text: str, target: str | None) -> tuple[str, str | None]:
    """Return (target, source) for the prompt; source None lets the model detect."""
    # Text without kana, e.g. Chinese, is treated as non-Japanese.
    is_japanese = _KANA.search(text) is not None
    resolved = target or ("en" if is_japanese else "ja")
    # Kana in text forced to Japanese may be mixed-language, so the source is
    # left to the model rather than declared as ja and translated ja->ja.
    source = "ja" if is_japanese and resolved != "ja" else None
    return resolved, source


def build_prompt(text: str, target: str, source: str | None = None) -> str:
    source_attr = f"<|plamo:key|>lang<|plamo:val|>{source}" if source else ""
    return (
        "<|plamo:tag|>dataset<|plamo:msg|>translation"
        f"<|plamo:tag|>input{source_attr}<|plamo:msg|>{text}"
        f"<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>{target}<|plamo:msg|>"
    )


def validate_text(text: str, max_chars: int) -> str:
    stripped = text.strip()
    if not stripped:
        raise ServiceError("翻訳するテキストを指定してください。")
    if len(stripped) > max_chars:
        raise ServiceError(f"翻訳できるのは {max_chars} 文字までです。")
    # PFML3 の制御トークンを本文から注入させない。
    if "<|plamo:" in stripped:
        raise ServiceError("翻訳できない文字列が含まれています。")
    return stripped


class TranslationClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def check_ready(self) -> None:
        try:
            response = requests.get(f"{self.base_url}/health", timeout=(1, 2))
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ExternalAPIError("Translation server health check failed.") from exc

    def translate(self, text: str, target: str, source: str | None = None) -> str:
        try:
            response = requests.post(
                f"{self.base_url}/v1/completions",
                json={
                    "model": self.model,
                    "prompt": build_prompt(text, target, source),
                    "temperature": 0,
                    "max_tokens": MAX_NEW_TOKENS,
                    "stop": list(STOP_TOKENS),
                },
                timeout=(5, TRANSLATE_TIMEOUT_SECONDS),
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ExternalAPIError("Translation request failed.") from exc

        try:
            translation = payload["choices"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExternalAPIError("Unexpected translation response.") from exc
        if not isinstance(translation, str) or not translation.strip():
            raise ExternalAPIError("Empty translation response.")
        return translation.strip()


class TranslateCommands(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        client: TranslationClient,
        engine: PodmanEngine,
        max_chars: int,
    ) -> None:
        self.bot = bot
        self.client = client
        self.engine = engine
        self.max_chars = max_chars
        self.active_requests = 0
        self.context_menu = make_message_context_menu(self)

    async def cog_load(self) -> None:
        self.bot.tree.add_command(self.context_menu)
        self.engine.start_idle_watch()

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(
            self.context_menu.name, type=discord.AppCommandType.message
        )
        await self.engine.shutdown()

    async def _translate(
        self,
        interaction: discord.Interaction,
        text: str,
        target: str | None = None,
    ) -> None:
        resolved_target, source = choose_languages(text, target)
        max_chars = (
            min(self.max_chars, MAX_CHARS_TO_ENGLISH)
            if resolved_target == "en"
            else self.max_chars
        )
        try:
            text = validate_text(text, max_chars)
        except ServiceError as exc:
            await send_interaction(interaction, str(exc))
            return
        if self.active_requests >= MAX_CONCURRENT_REQUESTS:
            await send_interaction(
                interaction, "現在混雑しています。しばらくしてから再度お試しください。"
            )
            return

        # Counted before the defer await so concurrent requests see it
        self.active_requests += 1
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            translation = await self.engine.call(
                self.client.translate, text, resolved_target, source
            )
        except ExternalAPIError:
            logger.warning(
                "Translation request failed: user=%s channel=%s chars=%s",
                format_log_user(interaction.user),
                format_log_channel(interaction.channel, interaction.channel_id),
                len(text),
            )
            await send_interaction(interaction, "翻訳結果を取得できませんでした。")
            return
        except Exception:
            logger.exception(
                "Unexpected translation error: user=%s channel=%s chars=%s",
                format_log_user(interaction.user),
                format_log_channel(interaction.channel, interaction.channel_id),
                len(text),
            )
            await send_interaction(interaction, "翻訳中にエラーが発生しました。")
            return
        finally:
            self.active_requests -= 1

        if len(translation) > MAX_MESSAGE_CONTENT_LENGTH:
            translation = translation[: MAX_MESSAGE_CONTENT_LENGTH - 3] + "..."
        await send_interaction(interaction, translation)

    @app_commands.command(
        name="translate",
        description="テキストを日本語または英語に翻訳します。",
        extras={
            "help": "仮名を含む文は英語へ、それ以外は日本語へ翻訳します。\n"
            "翻訳先は `target` で指定できます。結果は実行者だけに表示します。\n"
            "例: `/translate text:この問題の解き方を教えてください`"
        },
    )
    @app_commands.describe(
        text="翻訳するテキスト",
        target="翻訳先 (省略時は自動)",
    )
    @app_commands.choices(
        target=[
            app_commands.Choice(name="自動", value="auto"),
            app_commands.Choice(name="日本語", value="ja"),
            app_commands.Choice(name="English", value="en"),
        ]
    )
    async def translate_text(
        self,
        interaction: discord.Interaction,
        text: str,
        target: str = "auto",
    ) -> None:
        await self._translate(interaction, text, None if target == "auto" else target)

    async def translate_message(
        self, interaction: discord.Interaction, message: discord.Message
    ) -> None:
        if not message.content.strip():
            await send_interaction(
                interaction, "本文のあるメッセージを対象にしてください。"
            )
            return
        await self._translate(interaction, message.content)


def make_message_context_menu(cog: TranslateCommands) -> app_commands.ContextMenu:
    @app_commands.context_menu(name="メッセージを翻訳")
    async def translate_message(
        interaction: discord.Interaction, message: discord.Message
    ) -> None:
        await cog.translate_message(interaction, message)

    return translate_message


async def setup(bot: commands.Bot) -> None:
    settings = get_runtime(bot).settings
    if settings.translate_api_url is None:
        logger.info("Translation disabled (TRANSLATE_API_URL is not set)")
        return
    client = TranslationClient(settings.translate_api_url, settings.translate_model)
    engine = PodmanEngine(
        client.check_ready,
        settings.translate_container,
        "Translation server",
        ready_timeout=READY_TIMEOUT_SECONDS,
    )
    await bot.add_cog(
        TranslateCommands(bot, client, engine, settings.translate_max_chars)
    )
