import datetime
import os
import tempfile
import unittest
from contextlib import suppress
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from bot.db import Database
from bot.errors import ExternalAPIError
from bot.features.alpacahack import (
    AlpacaHackClient,
    SolveRecord,
    WeeklySolveSummary,
    _build_summary_embed,
    collect_weekly_summary,
    get_week_range,
    select_weekly_solves,
)


class AlpacaHackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tz = ZoneInfo("Asia/Tokyo")

    def test_get_week_range(self) -> None:
        self.assertEqual(
            get_week_range(datetime.date(2026, 6, 15)),
            (datetime.date(2026, 6, 15), datetime.date(2026, 6, 21)),
        )
        self.assertEqual(
            get_week_range(datetime.date(2026, 6, 21)),
            (datetime.date(2026, 6, 15), datetime.date(2026, 6, 21)),
        )

    def test_select_weekly_solves_filters_and_deduplicates(self) -> None:
        records = [
            SolveRecord(
                "old", "https://a/old", datetime.datetime(2026, 6, 14, tzinfo=self.tz)
            ),
            SolveRecord(
                "one", "https://a/1", datetime.datetime(2026, 6, 15, tzinfo=self.tz)
            ),
            SolveRecord(
                "dup", "https://a/1", datetime.datetime(2026, 6, 16, tzinfo=self.tz)
            ),
            SolveRecord("two", None, datetime.datetime(2026, 6, 17, tzinfo=self.tz)),
        ]
        selected = select_weekly_solves(
            records,
            week_start=datetime.date(2026, 6, 15),
            week_end=datetime.date(2026, 6, 21),
        )
        self.assertEqual([record.challenge_name for record in selected], ["one", "two"])

    @patch("bot.features.alpacahack.requests.get")
    def test_fetch_solve_records_parses_html(self, get: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.text = """
        <table>
          <tr>
            <td><a href="/challenges/example">Example</a></td>
            <td>33 solves</td>
            <td><span aria-label="2026-06-15 12:34:56 GMT+0">2026/06/15 12:34</span></td>
          </tr>
        </table>
        """
        get.return_value = response
        client = AlpacaHackClient(timezone=self.tz)
        records = client.fetch_solve_records("alice")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].challenge_name, "Example")
        self.assertEqual(
            records[0].challenge_url, "https://alpacahack.com/challenges/example"
        )
        self.assertEqual(records[0].solved_at.hour, 21)

    def test_collect_weekly_summary_mixes_success_and_failure(self) -> None:
        fd, path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(path)
        try:
            db = Database(path)
            db.add_alpacahack_user("alice")
            db.add_alpacahack_user("bob")
            client = Mock()
            client.fetch_solve_records.side_effect = [
                [
                    SolveRecord(
                        "Example",
                        None,
                        datetime.datetime(2026, 6, 15, 12, tzinfo=self.tz),
                    )
                ],
                ExternalAPIError("failed"),
            ]
            summary = collect_weekly_summary(
                db,
                client,
                timezone=self.tz,
                reference_date=datetime.date(2026, 6, 17),
                request_interval=0,
            )
            self.assertEqual(summary.total_users, 2)
            self.assertEqual(len(summary.weekly_solves["alice"]), 1)
            self.assertEqual(summary.failed_users, ["bob"])
        finally:
            for suffix in ("", "-wal", "-shm"):
                with suppress(FileNotFoundError):
                    os.unlink(path + suffix)

    def test_summary_embed_limits_fields(self) -> None:
        summary = WeeklySolveSummary(
            week_start=datetime.date(2026, 6, 15),
            week_end=datetime.date(2026, 6, 21),
            total_users=30,
            weekly_solves={f"user{i:02d}": [] for i in range(30)},
            failed_users=["failed"],
        )
        embed = _build_summary_embed(summary)
        self.assertLessEqual(len(embed.fields), 25)
        self.assertEqual(embed.fields[-1].name, "その他 / 取得失敗")


if __name__ == "__main__":
    unittest.main()
