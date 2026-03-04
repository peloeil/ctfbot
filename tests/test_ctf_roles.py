import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

import discord

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from bot.db.connection import DatabaseConnectionFactory  # noqa: E402
from bot.db.migrations import apply_migrations  # noqa: E402
from bot.features.ctf_roles.cog import CTFRoleCampaigns  # noqa: E402
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
                discussion_channel_id=500,
                voice_channel_id=600,
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
            self.assertEqual(found.discussion_channel_id, 500)
            self.assertEqual(found.voice_channel_id, 600)

            closed = usecase.close_campaign(campaign_id=campaign.id)
            self.assertTrue(closed.was_closed)
            self.assertIsNotNone(closed.closed_at_unix)
            self.assertIsNotNone(closed.archive_at_unix)
            assert closed.closed_at_unix is not None
            assert closed.archive_at_unix is not None
            self.assertGreater(closed.archive_at_unix, closed.closed_at_unix)
            active = usecase.list_campaigns(guild_id=1, status="active")
            closed_rows = usecase.list_campaigns(guild_id=1, status="closed")
            self.assertEqual(active, [])
            self.assertEqual(len(closed_rows), 1)
            self.assertEqual(closed_rows[0].ctf_name, "SECCON CTF")
            self.assertIsNotNone(closed_rows[0].archive_at_unix)

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
                discussion_channel_id=501,
                voice_channel_id=601,
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
                    discussion_channel_id=500 + index,
                    voice_channel_id=600 + index,
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

    def test_due_archives_detected_and_marked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            usecase, service = self._build_usecase(str(db_path))
            draft = CampaignDraft(
                ctf_name="ArchiveTarget CTF",
                start_at_unix=service.now_unix(),
                end_at_unix=None,
            )
            campaign = usecase.create_campaign(
                guild_id=1,
                channel_id=100,
                message_id=302,
                role_id=402,
                discussion_channel_id=502,
                voice_channel_id=602,
                created_by=10,
                draft=draft,
            )
            close_result = usecase.close_campaign(campaign_id=campaign.id)
            self.assertTrue(close_result.was_closed)

            factory = DatabaseConnectionFactory(database_path=str(db_path))
            past_unix = service.now_unix() - 1
            with factory.connection() as conn:
                conn.execute(
                    """
                    UPDATE ctf_role_campaign
                    SET archive_at_unix = ?
                    WHERE id = ?
                    """,
                    (past_unix, campaign.id),
                )
                conn.commit()

            due = usecase.list_due_archives(limit=10)
            self.assertIn(campaign.id, [row.id for row in due])

            marked = usecase.mark_campaign_archived(campaign_id=campaign.id)
            self.assertTrue(marked)
            due_after_mark = usecase.list_due_archives(limit=10)
            self.assertNotIn(campaign.id, [row.id for row in due_after_mark])

    def test_due_starts_detected_and_marked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ctfbot.db"
            usecase, service = self._build_usecase(str(db_path))
            now_unix = service.now_unix()
            draft = CampaignDraft(
                ctf_name="StartTarget CTF",
                start_at_unix=now_unix - 60,
                end_at_unix=now_unix + 3600,
            )
            campaign = usecase.create_campaign(
                guild_id=1,
                channel_id=100,
                message_id=303,
                role_id=403,
                discussion_channel_id=503,
                voice_channel_id=603,
                created_by=10,
                draft=draft,
            )

            due = usecase.list_due_starts(limit=10)
            self.assertIn(campaign.id, [row.id for row in due])

            marked = usecase.mark_campaign_started(campaign_id=campaign.id)
            self.assertTrue(marked)
            due_after_mark = usecase.list_due_starts(limit=10)
            self.assertNotIn(campaign.id, [row.id for row in due_after_mark])


class CTFRoleCogHelperTests(unittest.TestCase):
    def test_build_channel_base_name_normalizes_text(self) -> None:
        channel_name = CTFRoleCampaigns._build_channel_base_name(
            "  SECCON CTF 13 Finals!!  "
        )
        self.assertEqual(channel_name, "seccon-ctf-13-finals")

    def test_build_channel_base_name_falls_back_when_empty(self) -> None:
        channel_name = CTFRoleCampaigns._build_channel_base_name("!!!")
        self.assertEqual(channel_name, "ctf")

    def test_parse_role_color_accepts_hex(self) -> None:
        parsed, error = CTFRoleCampaigns._parse_role_color("#12AB34")
        self.assertEqual(parsed, 0x12AB34)
        self.assertEqual(error, "")

    def test_parse_role_color_accepts_0x_prefix(self) -> None:
        parsed, error = CTFRoleCampaigns._parse_role_color("0xff6600")
        self.assertEqual(parsed, 0xFF6600)
        self.assertEqual(error, "")

    def test_parse_role_color_rejects_invalid_value(self) -> None:
        parsed, error = CTFRoleCampaigns._parse_role_color("orange")
        self.assertIsNone(parsed)
        self.assertIn("16進数", error)

    def test_role_color_suggestions_show_preview(self) -> None:
        choices = CTFRoleCampaigns._build_role_color_suggestions("")
        self.assertGreater(len(choices), 0)
        self.assertIn("🟥", choices[0].name)
        self.assertTrue(choices[0].value.startswith("#"))

    def test_role_color_suggestions_filter_by_hex(self) -> None:
        choices = CTFRoleCampaigns._build_role_color_suggestions("22c55e")
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].value, "#22c55e")

    def test_build_discussion_overwrites_include_bot_member(self) -> None:
        default_role = discord.Object(id=1)
        role = discord.Object(id=2)
        creator = discord.Object(id=3)
        bot_member = discord.Object(id=4)

        overwrites = CTFRoleCampaigns._build_discussion_channel_overwrites(
            default_role=default_role,
            role=role,
            creator=creator,
            bot_member=bot_member,
        )

        self.assertIn(default_role, overwrites)
        self.assertEqual(overwrites[default_role].view_channel, False)
        self.assertIn(role, overwrites)
        self.assertIn(creator, overwrites)
        self.assertIn(bot_member, overwrites)
        self.assertEqual(overwrites[bot_member].view_channel, True)
        self.assertEqual(overwrites[bot_member].send_messages, True)


if __name__ == "__main__":
    unittest.main()
