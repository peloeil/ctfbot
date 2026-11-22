import os
import tempfile
import unittest
from contextlib import suppress
from unittest import mock
from zoneinfo import ZoneInfo

from ctfbot.db import Database
from ctfbot.errors import ServiceError
from ctfbot.features.ctfteam import campaign
from ctfbot.features.ctfteam.models import ActiveCampaign, CampaignStatus

NOW = 1_000
JST = ZoneInfo("Asia/Tokyo")
# 2026-01-01 10:00 JST
START_UNIX = 1_767_229_200


def parse(
    ctf_name: str = "Example",
    start_at_raw: str = "2026-01-01 10:00",
    end_at_raw: str = "",
):
    return campaign.parse_campaign_draft(
        ctf_name=ctf_name,
        start_at_raw=start_at_raw,
        end_at_raw=end_at_raw,
        timezone=JST,
    )


class ParseCampaignDraftTest(unittest.TestCase):
    def test_name_whitespace_is_normalized(self) -> None:
        self.assertEqual(parse(ctf_name="  Example   CTF ").ctf_name, "Example CTF")

    def test_datetimes_are_interpreted_in_the_given_timezone(self) -> None:
        draft = parse(start_at_raw="2026-01-01 10:00", end_at_raw="2026-01-02 10:00")

        self.assertEqual(draft.start_at_unix, START_UNIX)
        self.assertEqual(draft.end_at_unix, START_UNIX + 24 * 60 * 60)

    def test_empty_end_means_permanent_campaign(self) -> None:
        self.assertIsNone(parse(end_at_raw="  ").end_at_unix)

    def test_name_of_60_characters_is_accepted(self) -> None:
        self.assertEqual(parse(ctf_name="x" * 60).ctf_name, "x" * 60)

    def test_invalid_input_is_rejected_with_reason(self) -> None:
        cases = {
            "empty name": (
                {"ctf_name": ""},
                "CTF名を入力してください。",
            ),
            "blank name": (
                {"ctf_name": "  　 "},
                "CTF名を入力してください。",
            ),
            "name of 61 characters": (
                {"ctf_name": "x" * 61},
                "CTF名が長すぎます。60文字以内で入力してください。",
            ),
            "unparsable start": (
                {"start_at_raw": "bad"},
                "開始/終了日時の形式が不正です。",
            ),
            "unparsable end": (
                {"end_at_raw": "2026-13-01 10:00"},
                "開始/終了日時の形式が不正です。",
            ),
            "end before start": (
                {"end_at_raw": "2026-01-01 09:59"},
                "終了日時は開始日時より後にしてください。",
            ),
            "end equal to start": (
                {"end_at_raw": "2026-01-01 10:00"},
                "終了日時は開始日時より後にしてください。",
            ),
        }
        for label, (kwargs, message) in cases.items():
            with (
                self.subTest(label),
                self.assertRaisesRegex(ServiceError, message),
            ):
                parse(**kwargs)


class EnsureCampaignCanBeCreatedTest(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.addCleanup(self.remove_db)
        self.db = Database(self.path)

    def remove_db(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            with suppress(FileNotFoundError):
                os.unlink(self.path + suffix)

    def create_campaign(self, name: str, created_by: int, message_id: int):
        return self.db.create_campaign(
            channel_id=2,
            message_id=message_id,
            role_id=3,
            discussion_channel_id=4,
            voice_channel_id=5,
            ctf_name=name,
            start_at_unix=START_UNIX,
            end_at_unix=None,
            created_by=created_by,
            created_at_unix=1,
            max_active_per_creator=5,
        )

    def ensure(self, name: str = "New", created_by: int = 10) -> None:
        campaign.ensure_campaign_can_be_created(
            self.db, created_by=created_by, draft=parse(ctf_name=name)
        )

    def test_creator_below_active_limit_is_accepted(self) -> None:
        for index in range(4):
            self.create_campaign(f"CTF {index}", created_by=10, message_id=100 + index)

        self.ensure()

    def test_creator_at_active_limit_is_rejected_with_limit_in_message(self) -> None:
        for index in range(5):
            self.create_campaign(f"CTF {index}", created_by=10, message_id=100 + index)

        with self.assertRaisesRegex(
            ServiceError,
            r"同時に作成できる active 募集数の上限に達しています。\(上限: 5\)",
        ):
            self.ensure()

    def test_other_creators_campaigns_do_not_count_toward_limit(self) -> None:
        for index in range(5):
            self.create_campaign(f"CTF {index}", created_by=99, message_id=100 + index)

        self.ensure(created_by=10)

    def test_active_name_is_rejected_regardless_of_case(self) -> None:
        self.create_campaign("Same", created_by=10, message_id=100)

        with self.assertRaisesRegex(
            ServiceError, "同名の active 募集が既に存在します。"
        ):
            self.ensure(name="same", created_by=20)

    def test_name_of_closed_campaign_can_be_reused(self) -> None:
        item = self.create_campaign("Same", created_by=10, message_id=100)
        self.db.close_campaign(item.id, 201, 300)

        self.ensure(name="Same", created_by=20)


class CampaignTimeTest(unittest.TestCase):
    @staticmethod
    def make_campaign(start_at_unix: int, end_at_unix: int | None) -> ActiveCampaign:
        return ActiveCampaign(
            id=1,
            channel_id=2,
            message_id=3,
            role_id=4,
            ctf_name="Example",
            start_at_unix=start_at_unix,
            end_at_unix=end_at_unix,
            status=CampaignStatus.ACTIVE,
            created_by=7,
            created_at_unix=0,
        )

    def test_archive_is_scheduled_30_days_after_close(self) -> None:
        with mock.patch.object(campaign, "now_unix", return_value=NOW):
            closed_at, archive_at = campaign.calculate_close()

        self.assertEqual((closed_at, archive_at), (NOW, NOW + 30 * 24 * 60 * 60))

    def test_campaign_is_expired_from_its_end_time_on(self) -> None:
        cases = {
            "before end": (NOW + 1, False),
            "at end": (NOW, True),
            "after end": (NOW - 1, True),
            "permanent": (None, False),
        }
        for label, (end_at_unix, expected) in cases.items():
            with (
                self.subTest(label),
                mock.patch.object(campaign, "now_unix", return_value=NOW),
            ):
                self.assertIs(
                    campaign.is_expired(self.make_campaign(0, end_at_unix)), expected
                )

    def test_campaign_is_started_from_its_start_time_on(self) -> None:
        cases = {
            "before start": (NOW + 1, False),
            "at start": (NOW, True),
            "after start": (NOW - 1, True),
        }
        for label, (start_at_unix, expected) in cases.items():
            with (
                self.subTest(label),
                mock.patch.object(campaign, "now_unix", return_value=NOW),
            ):
                self.assertIs(
                    campaign.is_started(self.make_campaign(start_at_unix, None)),
                    expected,
                )
