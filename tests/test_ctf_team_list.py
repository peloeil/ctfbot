import unittest

from bot.features.ctf_team.cog import _build_campaigns_embed
from bot.features.ctf_team.models import ActiveCampaign, Campaign, CampaignStatus


class CampaignListEmbedTest(unittest.TestCase):
    def test_long_campaigns_fit_with_correct_omission_count(self) -> None:
        campaigns: list[Campaign] = [
            ActiveCampaign(
                id=index,
                channel_id=2,
                message_id=index,
                role_id=4,
                ctf_name="x" * 1000,
                start_at_unix=100,
                end_at_unix=200,
                status=CampaignStatus.ACTIVE,
                created_by=7,
                created_at_unix=90,
            )
            for index in range(1, 21)
        ]

        description = _build_campaigns_embed(1, campaigns, "募集中").description or ""
        shown = description.count("\n\n**")

        self.assertLessEqual(len(description), 4096)
        self.assertIn(f"他 {len(campaigns) - shown} 件は省略しています。", description)


if __name__ == "__main__":
    unittest.main()
