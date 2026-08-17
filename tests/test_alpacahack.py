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

from ctfbot.db import Database
from ctfbot.errors import ConflictError, ExternalAPIError
from ctfbot.features.alpacahack.cog import (
    Alpacahack,
    _build_daily_embed,
    _build_summary_embed,
)
from ctfbot.features.alpacahack.service import (
    AlpacaHackClient,
    DailyChallenge,
    SolveRecord,
    WeeklySolveSummary,
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

    @patch("ctfbot.features.alpacahack.service.requests.get")
    def test_fetch_daily_challenge_parses_description_and_attachments(
        self, get: Mock
    ) -> None:
        index_response = Mock()
        index_response.raise_for_status.return_value = None
        index_response.text = r"""
        <div>
          <span>Today's Challenge</span>
          <a href="/daily/challenges/example">
            <span>alice</span><span>Example</span><span>Misc</span>
            <span>Crypto</span><span>Easy</span><span>10 solves</span>
          </a>
        </div>
        <script>enqueue("[\"activeEndsAt\",\"2026-06-16T15:00:00.000Z\"]")</script>
        """
        challenge_response = Mock()
        challenge_response.raise_for_status.return_value = None
        challenge_response.text = r"""
        <html><head><meta name="description" content="fallback"></head><body>
          <h1>Example Challenge</h1>
          <div>
            <style>.description { color: orange; }</style>
            <p node="[object Object]">Recover the flag.</p>
            <details><summary>Beginner Hint</summary>Read the source.</details>
          </div>
          <a href="https://alpacahack-prod.s3.ap-northeast-1.amazonaws.com/id/example.tar.gz">example.tar.gz</a>
          <script>enqueue("[\"releaseAt\",[\"D\",1781449200000]]")</script>
        </body></html>
        """
        get.side_effect = [index_response, challenge_response]

        challenge = AlpacaHackClient(timezone=self.tz).fetch_daily_challenge()

        self.assertEqual(
            challenge,
            DailyChallenge(
                title="Example Challenge",
                url="https://alpacahack.com/daily/challenges/example",
                author="alice",
                categories=("Misc", "Crypto"),
                difficulty="Easy",
                description="Recover the flag.\n\nBeginner Hint\n||Read the source.||",
                attachment_urls=(
                    "https://alpacahack-prod.s3.ap-northeast-1.amazonaws.com/"
                    "id/example.tar.gz",
                ),
                starts_at=datetime.datetime(2026, 6, 15, tzinfo=self.tz),
                ends_at=datetime.datetime(2026, 6, 17, tzinfo=self.tz),
            ),
        )

    @patch("ctfbot.features.alpacahack.service.requests.get")
    def test_fetch_daily_challenge_returns_none_without_active_challenge(
        self, get: Mock
    ) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.text = "<div><span>Today's Challenge</span></div>"
        get.return_value = response

        challenge = AlpacaHackClient(timezone=self.tz).fetch_daily_challenge()

        self.assertIsNone(challenge)
        get.assert_called_once()

    @patch("ctfbot.features.alpacahack.service.requests.get")
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

    @patch("ctfbot.features.alpacahack.service.requests.get")
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

    @patch("ctfbot.features.alpacahack.service.requests.get")
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
            db.add_alpacahack_user("alice", max_users=50)
            db.add_alpacahack_user("bob", max_users=50)
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

    def test_daily_embed_links_attachment_and_limits_description(self) -> None:
        challenge = DailyChallenge(
            title="Example",
            url="https://alpacahack.com/daily/challenges/example",
            author="alice",
            categories=("Pwn",),
            difficulty="Medium",
            description="x" * 4000,
            attachment_urls=(
                "https://alpacahack-prod.s3.ap-northeast-1.amazonaws.com/"
                "id/example%20file.tar.gz",
            ),
            starts_at=datetime.datetime(2026, 6, 15, tzinfo=self.tz),
            ends_at=datetime.datetime(2026, 6, 17, tzinfo=self.tz),
        )

        embed = _build_daily_embed(challenge)

        self.assertEqual(len(embed.description or ""), 3500)
        self.assertEqual(
            embed.fields[0].value,
            "<t:1781449200:f> 〜 <t:1781622000:f>\n終了 <t:1781622000:R>",
        )
        self.assertEqual(embed.fields[1].value, "Pwn / Medium")
        self.assertEqual(
            embed.fields[3].value,
            "- [example file.tar.gz](https://alpacahack-prod.s3.ap-northeast-1."
            "amazonaws.com/id/example%20file.tar.gz)",
        )

    def test_daily_embed_closes_truncated_hint_spoiler(self) -> None:
        challenge = DailyChallenge(
            title="Example",
            url="https://alpacahack.com/daily/challenges/example",
            author="alice",
            categories=("Pwn",),
            difficulty="Medium",
            description="Beginner Hint\n||" + "x" * 4000 + "||",
            attachment_urls=(),
            starts_at=datetime.datetime(2026, 6, 15, tzinfo=self.tz),
            ends_at=datetime.datetime(2026, 6, 17, tzinfo=self.tz),
        )

        embed = _build_daily_embed(challenge)

        self.assertEqual(len(embed.description or ""), 3500)
        self.assertTrue((embed.description or "").endswith("...||"))


class AlpacaHackCommandTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cog: Any = object.__new__(Alpacahack)
        self.cog.bot = Mock()
        self.cog.db = Mock()
        self.cog.client = Mock()
        self.cog.settings = SimpleNamespace(
            tzinfo=ZoneInfo("Asia/Tokyo"), alpacahack_channel_id=10
        )
        self.defer = mock.AsyncMock()
        self.followup_send = mock.AsyncMock()
        self.interaction = cast(
            discord.Interaction,
            SimpleNamespace(
                guild=SimpleNamespace(id=1),
                response=SimpleNamespace(defer=self.defer),
                followup=SimpleNamespace(send=self.followup_send),
            ),
        )

    async def invoke_add(self, username: str) -> None:
        callback = self.cog.add_user.callback
        await callback(self.cog, self.interaction, username)

    async def test_daily_report_sends_only_after_new_challenge_is_reserved(
        self,
    ) -> None:
        challenge = DailyChallenge(
            title="Example",
            url="https://alpacahack.com/daily/challenges/example",
            author="alice",
            categories=("Misc",),
            difficulty="Easy",
            description="Recover the flag.",
            attachment_urls=(),
            starts_at=datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC),
            ends_at=datetime.datetime(2026, 6, 17, tzinfo=datetime.UTC),
        )
        self.cog.client.fetch_daily_challenge.return_value = challenge
        self.cog.db.reserve_alpacahack_daily_notification.side_effect = [True, False]
        channel = Mock()
        with (
            patch(
                "ctfbot.features.alpacahack.cog.resolve_messageable",
                new_callable=mock.AsyncMock,
                return_value=channel,
            ),
            patch(
                "ctfbot.features.alpacahack.cog.send_safely",
                new_callable=mock.AsyncMock,
            ) as send_safely,
        ):
            await self.cog.daily_challenge_report.coro(self.cog)
            await self.cog.daily_challenge_report.coro(self.cog)

        self.assertEqual(
            self.cog.db.reserve_alpacahack_daily_notification.call_count, 2
        )
        send_safely.assert_awaited_once()

    async def test_daily_command_displays_current_challenge_without_reserving(
        self,
    ) -> None:
        challenge = DailyChallenge(
            title="Example",
            url="https://alpacahack.com/daily/challenges/example",
            author="alice",
            categories=("Misc",),
            difficulty="Easy",
            description="Recover the flag.",
            attachment_urls=(),
            starts_at=datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC),
            ends_at=datetime.datetime(2026, 6, 17, tzinfo=datetime.UTC),
        )
        self.cog.client.fetch_daily_challenge.return_value = challenge

        await self.cog.show_daily.callback(self.cog, self.interaction)

        self.defer.assert_awaited_once()
        self.followup_send.assert_awaited_once_with(embed=_build_daily_embed(challenge))
        self.cog.db.reserve_alpacahack_daily_notification.assert_not_called()

    async def test_daily_command_reports_when_no_challenge_is_active(self) -> None:
        self.cog.client.fetch_daily_challenge.return_value = None
        with patch(
            "ctfbot.features.alpacahack.cog.send_interaction",
            new_callable=mock.AsyncMock,
        ) as send_interaction:
            await self.cog.show_daily.callback(self.cog, self.interaction)

        send_interaction.assert_awaited_once_with(
            self.interaction,
            "公開中の Daily AlpacaHack 問題はありません。",
            ephemeral=False,
        )
        self.cog.db.reserve_alpacahack_daily_notification.assert_not_called()

    async def test_daily_command_reports_fetch_failure(self) -> None:
        self.cog.client.fetch_daily_challenge.side_effect = ExternalAPIError("failed")
        with patch(
            "ctfbot.features.alpacahack.cog.send_interaction",
            new_callable=mock.AsyncMock,
        ) as send_interaction:
            await self.cog.show_daily.callback(self.cog, self.interaction)

        send_interaction.assert_awaited_once_with(
            self.interaction,
            "AlpacaHack からの取得に失敗しました。",
            ephemeral=False,
        )

    async def test_add_rejects_too_long_and_invalid_usernames(self) -> None:
        invalid_names = ["a" * 33, "invalid/name", "日本語"]
        with patch(
            "ctfbot.features.alpacahack.cog.send_interaction",
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
        self.cog.db.add_alpacahack_user.assert_not_called()

    async def test_add_accepts_32_character_username_with_dash_and_underscore(
        self,
    ) -> None:
        name = "a" * 29 + "-_x"
        self.cog.db.add_alpacahack_user.return_value = True
        with (
            patch(
                "ctfbot.features.alpacahack.cog.send_interaction",
                new_callable=mock.AsyncMock,
            ) as send_interaction,
            patch(
                "ctfbot.features.alpacahack.cog.log_audit",
                new_callable=mock.AsyncMock,
            ),
        ):
            await self.invoke_add(name)

        self.cog.db.add_alpacahack_user.assert_called_once_with(name, max_users=50)
        send_interaction.assert_awaited_once_with(
            self.interaction, f"`{name}` を登録しました。"
        )

    async def test_add_rejects_new_user_when_registration_limit_is_reached(
        self,
    ) -> None:
        self.cog.db.add_alpacahack_user.side_effect = ConflictError(
            "AlpacaHack user limit reached."
        )
        with (
            patch(
                "ctfbot.features.alpacahack.cog.send_interaction",
                new_callable=mock.AsyncMock,
            ) as send_interaction,
            patch(
                "ctfbot.features.alpacahack.cog.log_audit",
                new_callable=mock.AsyncMock,
            ) as log_audit,
        ):
            await self.invoke_add("new_user")

        send_interaction.assert_awaited_once_with(
            self.interaction, "登録数が上限(50人)に達しています。"
        )
        self.cog.db.add_alpacahack_user.assert_called_once_with(
            "new_user", max_users=50
        )
        log_audit.assert_not_awaited()

    async def test_add_reports_existing_user_when_registration_limit_is_reached(
        self,
    ) -> None:
        self.cog.db.add_alpacahack_user.return_value = False
        with (
            patch(
                "ctfbot.features.alpacahack.cog.send_interaction",
                new_callable=mock.AsyncMock,
            ) as send_interaction,
            patch(
                "ctfbot.features.alpacahack.cog.log_audit",
                new_callable=mock.AsyncMock,
            ) as log_audit,
        ):
            await self.invoke_add("alice")

        send_interaction.assert_awaited_once_with(
            self.interaction, "`alice` は既に登録されています。"
        )
        self.cog.db.add_alpacahack_user.assert_called_once_with("alice", max_users=50)
        log_audit.assert_not_awaited()
