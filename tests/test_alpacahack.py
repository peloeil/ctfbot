import datetime
import os
import tempfile
import unittest
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import discord

from bot.db import Database
from bot.errors import ExternalAPIError
from bot.features.alpacahack import (
    Alpacahack,
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
            <td><span aria-label="2026-06-15 12:34:56 GMT+0">
              2026/06/15 12:34
            </span></td>
          </tr>
        </table>
        """
        get.return_value = response
        client = AlpacaHackClient(timezone=self.tz)
        records = client.fetch_solve_records("alice", page_interval=0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].challenge_name, "Example")
        self.assertEqual(
            records[0].challenge_url, "https://alpacahack.com/challenges/example"
        )
        self.assertEqual(records[0].solved_at.hour, 21)

    @patch("bot.features.alpacahack.requests.get")
    def test_fetch_solve_records_skips_rows_with_invalid_datetime(
        self, get: Mock
    ) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.text = """
        <table>
          <tr>
            <td><a href="/challenges/bad">Bad</a></td>
            <td>1 solves</td>
            <td><span aria-label="2026-99-99 12:00 GMT+0">
              2026/99/99 12:00
            </span></td>
          </tr>
          <tr>
            <td><a href="/challenges/good">Good</a></td>
            <td>1 solves</td>
            <td><span aria-label="2026-06-15 12:00 GMT+0">
              2026/06/15 12:00
            </span></td>
          </tr>
        </table>
        """
        get.return_value = response
        client = AlpacaHackClient(timezone=self.tz)
        records = client.fetch_solve_records("alice", page_interval=0)
        self.assertEqual([record.challenge_name for record in records], ["Good"])

    @patch("bot.features.alpacahack.requests.get")
    def test_fetch_solve_records_paginates(self, get: Mock) -> None:
        def make_page(names: list[str]) -> Mock:
            rows = "\n".join(
                f'<tr><td><a href="/challenges/{n}">{n}</a></td>'
                f"<td>1 solves</td>"
                f'<td><span aria-label="2026-06-15 12:00 GMT+0">'
                f"2026/06/15 12:00</span></td></tr>"
                for n in names
            )
            resp = Mock()
            resp.raise_for_status.return_value = None
            resp.text = f"<table>{rows}</table>"
            return resp

        full_page = make_page([f"c{i}" for i in range(10)])
        partial_page = make_page(["last"])
        get.side_effect = [full_page, partial_page]
        client = AlpacaHackClient(timezone=self.tz)
        records = client.fetch_solve_records("alice", page_interval=0)
        self.assertEqual(len(records), 11)
        self.assertEqual(get.call_count, 2)

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

    def test_summary_embed_stays_within_total_limit_and_reports_omitted_users(
        self,
    ) -> None:
        solved_at = datetime.datetime(2026, 6, 15, tzinfo=self.tz)
        weekly_solves = {
            f"user{i:02d}": [SolveRecord("x" * 200, None, solved_at) for _ in range(12)]
            for i in range(24)
        }
        summary = WeeklySolveSummary(
            week_start=datetime.date(2026, 6, 15),
            week_end=datetime.date(2026, 6, 21),
            total_users=24,
            weekly_solves=weekly_solves,
            failed_users=[],
        )

        embed = _build_summary_embed(summary)
        total = (
            len(embed.title or "")
            + len(embed.description or "")
            + sum(
                len(field.name or "") + len(field.value or "") for field in embed.fields
            )
        )
        shown = len(embed.fields) - 1

        self.assertLessEqual(total, 6000)
        self.assertEqual(embed.fields[-1].name, "その他")
        self.assertEqual(
            embed.fields[-1].value,
            f"他 {len(weekly_solves) - shown} 人は省略しました。",
        )

    def test_summary_embed_renders_unsafe_challenge_name_without_link(self) -> None:
        summary = WeeklySolveSummary(
            week_start=datetime.date(2026, 6, 15),
            week_end=datetime.date(2026, 6, 21),
            total_users=1,
            weekly_solves={
                "alice": [
                    SolveRecord(
                        "broken)",
                        "https://example.test/challenge",
                        datetime.datetime(2026, 6, 15, tzinfo=self.tz),
                    )
                ]
            },
            failed_users=[],
        )

        embed = _build_summary_embed(summary)

        self.assertEqual(embed.fields[0].value, "- broken)")


class AlpacaHackCommandTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cog = object.__new__(Alpacahack)
        self.cog.bot = Mock()
        self.cog.db = Mock()
        self.cog.settings = SimpleNamespace(tzinfo=ZoneInfo("Asia/Tokyo"))
        self.interaction = cast(
            discord.Interaction,
            SimpleNamespace(guild=SimpleNamespace(id=1)),
        )

    async def invoke_add(self, username: str) -> None:
        callback = cast(Any, self.cog.add_user.callback)
        await callback(self.cog, self.interaction, username)

    async def test_add_rejects_too_long_and_invalid_usernames(self) -> None:
        invalid_names = ["a" * 33, "invalid/name", "日本語"]
        with patch(
            "bot.features.alpacahack.send_interaction",
            new_callable=mock.AsyncMock,
        ) as send_interaction:
            for name in invalid_names:
                with self.subTest(name=name):
                    await self.invoke_add(name)
                    send_interaction.assert_awaited_once_with(
                        self.interaction,
                        "ユーザー名は 32 文字以内の英数字と "
                        "`-` `_` で入力してください。",
                    )
                    send_interaction.reset_mock()
        self.cog.db.list_alpacahack_users.assert_not_called()

    async def test_add_accepts_32_character_username_with_dash_and_underscore(
        self,
    ) -> None:
        name = "a" * 29 + "-_x"
        self.cog.db.list_alpacahack_users.return_value = []
        self.cog.db.add_alpacahack_user.return_value = True
        with (
            patch(
                "bot.features.alpacahack.send_interaction",
                new_callable=mock.AsyncMock,
            ) as send_interaction,
            patch(
                "bot.features.alpacahack.log_audit",
                new_callable=mock.AsyncMock,
            ),
        ):
            await self.invoke_add(name)

        self.cog.db.add_alpacahack_user.assert_called_once_with(name)
        send_interaction.assert_awaited_once_with(
            self.interaction, f"`{name}` を登録しました。"
        )

    async def test_add_rejects_new_user_when_registration_limit_is_reached(
        self,
    ) -> None:
        self.cog.db.list_alpacahack_users.return_value = [
            f"user{i:02d}" for i in range(50)
        ]
        with patch(
            "bot.features.alpacahack.send_interaction",
            new_callable=mock.AsyncMock,
        ) as send_interaction:
            await self.invoke_add("new_user")

        send_interaction.assert_awaited_once_with(
            self.interaction, "登録数が上限(50人)に達しています。"
        )
        self.cog.db.add_alpacahack_user.assert_not_called()

    async def test_add_reports_existing_user_when_registration_limit_is_reached(
        self,
    ) -> None:
        users = [f"user{i:02d}" for i in range(49)] + ["alice"]
        self.cog.db.list_alpacahack_users.return_value = users
        with patch(
            "bot.features.alpacahack.send_interaction",
            new_callable=mock.AsyncMock,
        ) as send_interaction:
            await self.invoke_add("alice")

        send_interaction.assert_awaited_once_with(
            self.interaction, "`alice` は既に登録されています。"
        )
        self.cog.db.add_alpacahack_user.assert_not_called()


if __name__ == "__main__":
    unittest.main()
