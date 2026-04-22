import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import discord
from discord.ext import commands

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.command_audit import CommandAuditLogger, sanitize_audit_text  # noqa: E402


class _FakeBot(commands.Bot):
    def __init__(self, *, bot_channel_id: int = 123) -> None:
        intents = discord.Intents.none()
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.runtime = SimpleNamespace(
            settings=SimpleNamespace(bot_channel_id=bot_channel_id)
        )


class CommandAuditTests(unittest.IsolatedAsyncioTestCase):
    def test_sanitize_audit_text_collapses_newlines_and_escapes_mentions(self) -> None:
        sanitized = sanitize_audit_text("__SECCON__\n@everyone <@123>")

        self.assertNotIn("\n", sanitized)
        self.assertIn("\\_\\_SECCON", sanitized)
        self.assertNotIn("@everyone", sanitized)
        self.assertNotIn("<@123>", sanitized)

    def test_build_message_uses_safe_actor_label_location_and_details(self) -> None:
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=42, display_name="alice"),
            channel=SimpleNamespace(mention="#bot-log"),
        )
        typed_interaction = cast(discord.Interaction, interaction)

        message = CommandAuditLogger.build_message(
            typed_interaction,
            command_name="/ctfteam open",
            details=("CTF名: SECCON CTF", "結果: 募集を作成しました。"),
        )

        self.assertIn("`alice` (id=42)", message)
        self.assertNotIn("<@42>", message)
        self.assertIn("#bot-log", message)
        self.assertIn("`/ctfteam open`", message)
        self.assertIn("- CTF名: SECCON CTF", message)
        self.assertIn("- 結果: 募集を作成しました。", message)

    async def test_log_command_sends_to_configured_bot_channel(self) -> None:
        bot = _FakeBot()
        audit_logger = CommandAuditLogger(bot)
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=42, mention="<@42>"),
            channel=SimpleNamespace(mention="#bot-log"),
        )
        typed_interaction = cast(discord.Interaction, interaction)
        channel = SimpleNamespace()

        with (
            patch.object(
                audit_logger._gateway,
                "resolve_messageable_channel",
                new=AsyncMock(return_value=channel),
            ),
            patch(
                "bot.command_audit.send_message_safely",
                new=AsyncMock(),
            ) as send_mock,
        ):
            await audit_logger.log_command(
                typed_interaction,
                command_name="/times create",
                details=("作成: #web",),
            )

        send_mock.assert_awaited_once()
        await_args = send_mock.await_args
        assert await_args is not None
        self.assertEqual(await_args.args[0], channel)
        self.assertIn("`/times create`", await_args.kwargs["content"])
        allowed_mentions = await_args.kwargs["allowed_mentions"]
        self.assertFalse(allowed_mentions.everyone)
        self.assertFalse(allowed_mentions.users)
        self.assertFalse(allowed_mentions.roles)
        self.assertFalse(allowed_mentions.replied_user)
        await bot.close()


if __name__ == "__main__":
    unittest.main()
