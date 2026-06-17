import unittest
from types import SimpleNamespace
from typing import cast

import discord

from bot.features.ctf_team.discord_ops import (
    build_recruitment_message,
    normalize_channel_name,
)
from bot.features.ctf_team.models import CampaignDraft


class DiscordOpsTest(unittest.TestCase):
    def test_normalize_channel_name(self) -> None:
        self.assertEqual(normalize_channel_name("Example CTF 2026"), "example-ctf-2026")
        self.assertEqual(normalize_channel_name("  A---B!!! C  "), "a-b-c")
        self.assertEqual(normalize_channel_name("日本語"), "ctf")
        self.assertLessEqual(len(normalize_channel_name("a" * 200)), 100)

    def test_build_recruitment_message_with_end(self) -> None:
        role = cast(discord.Role, SimpleNamespace(mention="<@&1>"))
        channel = cast(discord.TextChannel, SimpleNamespace(mention="<#2>"))
        draft = CampaignDraft(
            ctf_name="Example",
            start_at_unix=1_800_000_000,
            end_at_unix=1_800_086_400,
        )
        message = build_recruitment_message(draft, role, channel)
        self.assertIn("📣 **Example** 参加者募集", message)
        self.assertIn("🕐 開始: <t:1800000000:f> (<t:1800000000:R>)", message)
        self.assertIn("🏁 終了: <t:1800086400:f> (<t:1800086400:R>)", message)
        self.assertIn("💬 CTFチャンネル: <#2>", message)
        self.assertIn("👥 ロール: <@&1>", message)

    def test_build_recruitment_message_for_permanent_ctf(self) -> None:
        role = cast(discord.Role, SimpleNamespace(mention="<@&1>"))
        channel = cast(discord.TextChannel, SimpleNamespace(mention="<#2>"))
        draft = CampaignDraft(
            ctf_name="Permanent",
            start_at_unix=1_800_000_000,
            end_at_unix=None,
        )
        message = build_recruitment_message(draft, role, channel)
        self.assertIn("🏁 終了: 常設", message)


if __name__ == "__main__":
    unittest.main()
