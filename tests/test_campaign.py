import os
import tempfile
import unittest
from contextlib import suppress
from zoneinfo import ZoneInfo

from bot.db import Database
from bot.errors import ServiceError
from bot.features.ctf_team import campaign


class CampaignLogicTest(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.db = Database(self.path)
        self.tz = ZoneInfo("Asia/Tokyo")

    def tearDown(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            with suppress(FileNotFoundError):
                os.unlink(self.path + suffix)

    def create_campaign(
        self, name: str = "Existing", created_by: int = 10, message_id: int = 100
    ):
        return self.db.create_campaign(
            guild_id=1,
            channel_id=2,
            message_id=message_id,
            role_id=3,
            discussion_channel_id=4,
            voice_channel_id=5,
            ctf_name=name,
            start_at_unix=campaign.to_unix(
                campaign.parse_datetime("2026-01-01 10:00", self.tz)
            ),
            end_at_unix=None,
            created_by=created_by,
            created_at_unix=1,
            max_active_per_creator=campaign.MAX_ACTIVE_PER_USER,
        )

    def test_validate_and_build_draft(self) -> None:
        draft = campaign.validate_and_build_draft(
            self.db,
            guild_id=1,
            created_by=10,
            ctf_name="  Example   CTF ",
            start_at_raw="2026-01-01 10:00",
            end_at_raw="2026-01-02 10:00",
            timezone=self.tz,
        )
        self.assertEqual(draft.ctf_name, "Example CTF")
        self.assertIsNotNone(draft.end_at_unix)
        assert draft.end_at_unix is not None
        self.assertLess(draft.start_at_unix, draft.end_at_unix)

    def test_invalid_names_and_datetime(self) -> None:
        cases = [
            {"ctf_name": "", "start_at_raw": "2026-01-01 10:00", "end_at_raw": ""},
            {
                "ctf_name": "x" * 61,
                "start_at_raw": "2026-01-01 10:00",
                "end_at_raw": "",
            },
            {"ctf_name": "Valid", "start_at_raw": "bad", "end_at_raw": ""},
            {
                "ctf_name": "Valid",
                "start_at_raw": "2026-01-02 10:00",
                "end_at_raw": "2026-01-01 10:00",
            },
        ]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ServiceError):
                campaign.validate_and_build_draft(
                    self.db, guild_id=1, created_by=10, timezone=self.tz, **kwargs
                )

    def test_active_limit(self) -> None:
        for i in range(campaign.MAX_ACTIVE_PER_USER):
            self.create_campaign(name=f"CTF {i}", message_id=100 + i)
        with self.assertRaises(ServiceError):
            campaign.validate_and_build_draft(
                self.db,
                guild_id=1,
                created_by=10,
                ctf_name="New",
                start_at_raw="2026-01-01 10:00",
                end_at_raw="",
                timezone=self.tz,
            )

    def test_duplicate_active_name(self) -> None:
        self.create_campaign(name="Same")
        with self.assertRaises(ServiceError):
            campaign.validate_and_build_draft(
                self.db,
                guild_id=1,
                created_by=20,
                ctf_name="same",
                start_at_raw="2026-01-01 10:00",
                end_at_raw="",
                timezone=self.tz,
            )

    def test_calculate_close(self) -> None:
        closed_at, archive_at = campaign.calculate_close(self.tz)
        self.assertEqual(archive_at - closed_at, 30 * 24 * 60 * 60)

    def test_started_and_expired(self) -> None:
        now = campaign.now_unix(self.tz)
        past = self.create_campaign(name="Past", message_id=1)
        future = self.create_campaign(name="Future", message_id=2)
        permanent = self.create_campaign(name="Permanent", message_id=3)
        past = self.db.create_campaign(
            guild_id=2,
            channel_id=2,
            message_id=4,
            role_id=3,
            discussion_channel_id=None,
            voice_channel_id=None,
            ctf_name="Expired",
            start_at_unix=now - 20,
            end_at_unix=now - 10,
            created_by=1,
            created_at_unix=1,
            max_active_per_creator=campaign.MAX_ACTIVE_PER_USER,
        )
        future = self.db.create_campaign(
            guild_id=2,
            channel_id=2,
            message_id=5,
            role_id=3,
            discussion_channel_id=None,
            voice_channel_id=None,
            ctf_name="NotExpired",
            start_at_unix=now + 10,
            end_at_unix=now + 20,
            created_by=1,
            created_at_unix=1,
            max_active_per_creator=campaign.MAX_ACTIVE_PER_USER,
        )
        self.assertTrue(campaign.is_expired(past, self.tz))
        self.assertFalse(campaign.is_expired(future, self.tz))
        self.assertFalse(campaign.is_expired(permanent, self.tz))
        self.assertTrue(campaign.is_started(past, self.tz))
        self.assertFalse(campaign.is_started(future, self.tz))


if __name__ == "__main__":
    unittest.main()
