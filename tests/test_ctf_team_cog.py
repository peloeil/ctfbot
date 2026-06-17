import unittest
from dataclasses import replace

from bot.features.ctf_team.cog import _build_campaigns_embed
from bot.features.ctf_team.models import Campaign, CampaignStatus


class CTFTeamCogTest(unittest.TestCase):
    def campaign(self) -> Campaign:
        return Campaign(
            id=1,
            guild_id=10,
            channel_id=20,
            message_id=30,
            role_id=40,
            ctf_name="Example",
            start_at_unix=1_800_000_000,
            end_at_unix=None,
            status=CampaignStatus.ACTIVE,
            created_by=50,
            created_at_unix=1_799_999_000,
            discussion_channel_id=60,
            voice_channel_id=70,
        )

    def test_build_campaigns_embed_empty(self) -> None:
        embed = _build_campaigns_embed(10, [], "募集中")
        self.assertEqual(embed.title, "CTF募集一覧 (募集中)")
        self.assertEqual(embed.description, "該当する募集はありません。")

    def test_build_campaigns_embed_active_campaign(self) -> None:
        embed = _build_campaigns_embed(10, [self.campaign()], "募集中")
        description = embed.description or ""
        self.assertIn("1件を表示しています。", description)
        self.assertIn("**1. Example**", description)
        self.assertIn("状態: 募集中", description)
        self.assertIn("終了: 常設", description)
        self.assertIn("https://discord.com/channels/10/20/30", description)
        self.assertIn("議論: <#60>", description)
        self.assertIn("VC: <#70>", description)
        self.assertIn("ロール: <@&40>", description)
        self.assertIn("作成者: <@50>", description)

    def test_build_campaigns_embed_closed_campaign(self) -> None:
        embed = _build_campaigns_embed(
            10,
            [
                replace(
                    self.campaign(),
                    status=CampaignStatus.CLOSED,
                    end_at_unix=1_800_086_400,
                    archive_at_unix=1_802_678_400,
                )
            ],
            "終了",
        )
        description = embed.description or ""
        self.assertIn("状態: 終了", description)
        self.assertIn("終了: <t:1800086400:f> (<t:1800086400:R>)", description)
        self.assertIn("archive予定: <t:1802678400:f> (<t:1802678400:R>)", description)


if __name__ == "__main__":
    unittest.main()
