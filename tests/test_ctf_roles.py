import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.db.connection import DatabaseConnectionFactory  # noqa: E402
from bot.db.migrations import apply_migrations  # noqa: E402
from bot.features.ctf_roles.models import CampaignDraft, CampaignStatus  # noqa: E402
from bot.features.ctf_roles.repository import CTFRoleCampaignRepository  # noqa: E402
from bot.features.ctf_roles.service import CTFRoleService  # noqa: E402
from bot.features.ctf_roles.usecase import CTFRoleUseCase  # noqa: E402


class CTFRoleUseCaseTests(unittest.TestCase):
    def _build_usecase(self, db_path: str) -> tuple[CTFRoleUseCase, CTFRoleService]:
        factory = DatabaseConnectionFactory(database_path=db_path)
        apply_migrations(factory)
        repository = CTFRoleCampaignRepository(connection_factory=factory)
        service = CTFRoleService(timezone=ZoneInfo("Asia/Tokyo"))
        return CTFRoleUseCase(repository=repository, service=service), service

    def test_validate_campaign_draft_rejects_invalid_datetime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            usecase, _service = self._build_usecase(str(Path(tmpdir) / "ctfbot.db"))
            result = usecase.validate_campaign_draft(
                guild_id=1,
                created_by=10,
                ctf_name="TSG CTF",
                start_at_raw="2026/03/04 21:00",
                end_at_raw="",
            )

        self.assertFalse(result.is_valid)
        self.assertIn("YYYY-MM-DD HH:MM", result.error_message)

    def test_create_find_and_close_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            usecase, _service = self._build_usecase(str(Path(tmpdir) / "ctfbot.db"))
            draft_validation = usecase.validate_campaign_draft(
                guild_id=1,
                created_by=10,
                ctf_name="SECCON CTF",
                start_at_raw="2026-11-01 10:00",
                end_at_raw="2026-11-03 10:00",
            )
            self.assertTrue(draft_validation.is_valid)
            self.assertIsNotNone(draft_validation.draft)
            assert draft_validation.draft is not None

            campaign = usecase.create_campaign(
                guild_id=1,
                channel_id=100,
                message_id=200,
                role_id=300,
                created_by=10,
                draft=draft_validation.draft,
            )

            found = usecase.find_active_campaign_by_message(
                guild_id=1,
                channel_id=100,
                message_id=200,
            )
            self.assertIsNotNone(found)
            assert found is not None
            self.assertEqual(found.id, campaign.id)
            self.assertEqual(found.status, CampaignStatus.ACTIVE)

            closed = usecase.close_campaign(campaign_id=campaign.id)
            self.assertTrue(closed)
            active = usecase.list_campaigns(guild_id=1, status="active")
            closed_rows = usecase.list_campaigns(guild_id=1, status="closed")
            self.assertEqual(active, [])
            self.assertEqual(len(closed_rows), 1)
            self.assertEqual(closed_rows[0].ctf_name, "SECCON CTF")

    def test_due_campaigns_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            usecase, service = self._build_usecase(str(Path(tmpdir) / "ctfbot.db"))
            now = service.now()
            draft = CampaignDraft(
                ctf_name="Expired CTF",
                start_at_unix=service.to_unix(now - datetime.timedelta(days=2)),
                end_at_unix=service.to_unix(now - datetime.timedelta(days=1)),
            )
            created = usecase.create_campaign(
                guild_id=1,
                channel_id=100,
                message_id=201,
                role_id=301,
                created_by=10,
                draft=draft,
            )

            due = usecase.list_due_campaigns(limit=10)

        self.assertIn(created.id, [campaign.id for campaign in due])

    def test_active_campaign_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            usecase, service = self._build_usecase(str(Path(tmpdir) / "ctfbot.db"))
            now = service.now()
            for index in range(3):
                draft = CampaignDraft(
                    ctf_name=f"CTF-{index}",
                    start_at_unix=service.to_unix(now),
                    end_at_unix=None,
                )
                usecase.create_campaign(
                    guild_id=1,
                    channel_id=100,
                    message_id=300 + index,
                    role_id=400 + index,
                    created_by=10,
                    draft=draft,
                )

            validation = usecase.validate_campaign_draft(
                guild_id=1,
                created_by=10,
                ctf_name="Another CTF",
                start_at_raw="2026-12-01 10:00",
                end_at_raw="",
            )

        self.assertFalse(validation.is_valid)
        self.assertIn("上限", validation.error_message)


if __name__ == "__main__":
    unittest.main()

