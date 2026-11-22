import datetime
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import discord
import requests
from discord.ext import tasks

from ctfbot.db import Database
from ctfbot.errors import ExternalAPIError
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
from ctfbot.runtime import BotRuntime


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

    @patch("ctfbot.features.alpacahack.service.requests.Session.get")
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

    @patch("ctfbot.features.alpacahack.service.requests.Session.get")
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

    @patch("ctfbot.features.alpacahack.service.requests.Session.get")
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
        self.assertEqual(
            records,
            [
                SolveRecord(
                    "Example",
                    "https://alpacahack.com/challenges/example",
                    datetime.datetime(2026, 6, 15, 21, 34, 56, tzinfo=self.tz),
                )
            ],
        )

    @patch("ctfbot.features.alpacahack.service.requests.Session.get")
    def test_fetch_solve_records_decodes_utf8_without_charset(self, get: Mock) -> None:
        response = requests.Response()
        response.status_code = 200
        response.headers["Content-Type"] = "text/html"
        response._content = """
        <table>
          <tr>
            <td><a href="/challenges/example">括弧は禁止</a></td>
            <td>1 solve</td>
            <td><span aria-label="2026-06-15 12:00 GMT+0"></span></td>
          </tr>
        </table>
        """.encode()
        get.return_value = response

        records = AlpacaHackClient(timezone=self.tz).fetch_solve_records(
            "alice", page_interval=0
        )

        self.assertEqual(records[0].challenge_name, "括弧は禁止")

    @patch("ctfbot.features.alpacahack.service.requests.Session.get")
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

    @patch("ctfbot.features.alpacahack.service.requests.Session.get")
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
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db = Database(str(Path(tmp.name) / "test.db"))
        db.add_alpacahack_user("alice", max_users=50)
        db.add_alpacahack_user("bob", max_users=50)
        solve = SolveRecord(
            "Example", None, datetime.datetime(2026, 6, 15, 12, tzinfo=self.tz)
        )
        client = Mock()
        client.fetch_solve_records.side_effect = [[solve], ExternalAPIError("failed")]

        summary = collect_weekly_summary(
            db,
            client,
            timezone=self.tz,
            reference_date=datetime.date(2026, 6, 17),
            request_interval=0,
        )

        self.assertEqual(summary.total_users, 2)
        self.assertEqual(summary.weekly_solves, {"alice": [solve]})
        self.assertEqual(summary.failed_users, ["bob"])

    def test_summary_embed_limits_fields(self) -> None:
        summary = WeeklySolveSummary(
            week_start=datetime.date(2026, 6, 15),
            week_end=datetime.date(2026, 6, 21),
            total_users=30,
            weekly_solves={f"user{i:02d}": [] for i in range(30)},
            failed_users=["failed"],
        )
        embed = _build_summary_embed(summary)
        # 24 user fields plus one trailing field: Discord allows 25 per embed.
        self.assertEqual(len(embed.fields), 25)
        self.assertEqual(embed.fields[-1].name, "その他 / 取得失敗")
        self.assertEqual(
            embed.fields[-1].value, "他 6 人は省略しました。\n取得失敗: failed"
        )

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

        self.assertLessEqual(total, 6000)
        # Each user field is truncated to ~1KB, so only 4 fit before the 6000 cap.
        self.assertEqual(len(embed.fields), 5)
        self.assertEqual(embed.fields[-1].name, "その他")
        self.assertEqual(embed.fields[-1].value, "他 20 人は省略しました。")

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
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(
            fields["出題期間"],
            "<t:1781449200:f> 〜 <t:1781622000:f>\n終了 <t:1781622000:R>",
        )
        self.assertEqual(fields["カテゴリ / 難易度"], "Pwn / Medium")
        self.assertEqual(
            fields["添付ファイル"],
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


def make_challenge(url: str = "https://alpacahack.com/daily/challenges/example"):
    return DailyChallenge(
        title="Example",
        url=url,
        author="alice",
        categories=("Misc",),
        difficulty="Easy",
        description="Recover the flag.",
        attachment_urls=(),
        starts_at=datetime.datetime(2026, 6, 15, tzinfo=datetime.UTC),
        ends_at=datetime.datetime(2026, 6, 17, tzinfo=datetime.UTC),
    )


class AlpacaHackCommandTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database(str(Path(tmp.name) / "test.db"))
        tzinfo = ZoneInfo("Asia/Tokyo")
        self.settings = SimpleNamespace(
            tzinfo=tzinfo,
            alpacahack_channel_id=10,
            alpacahack_mention_id=None,
            alpacahack_daily_time=datetime.time(0, 5, tzinfo=tzinfo),
            alpacahack_solve_time=datetime.time(23, 0, tzinfo=tzinfo),
            guild_id=1,
        )
        self.bot = Mock()
        self.bot.runtime = BotRuntime(settings=cast(Any, self.settings), db=self.db)
        # The cog starts its report loops on construction; they are driven by hand.
        with (
            patch.object(tasks.Loop, "start"),
            patch("ctfbot.features.alpacahack.cog.AlpacaHackClient") as client_class,
        ):
            self.cog = Alpacahack(self.bot)
        self.client = client_class.return_value
        self.send_interaction = self.enterContext(
            patch(
                "ctfbot.features.alpacahack.cog.send_interaction",
                new_callable=mock.AsyncMock,
            )
        )
        self.log_audit = self.enterContext(
            patch(
                "ctfbot.features.alpacahack.cog.log_audit",
                new_callable=mock.AsyncMock,
            )
        )
        self.defer = mock.AsyncMock()
        self.followup_send = mock.AsyncMock()
        self.interaction = cast(
            discord.Interaction,
            SimpleNamespace(
                guild=SimpleNamespace(id=1),
                response=SimpleNamespace(defer=self.defer),
                followup=SimpleNamespace(send=self.followup_send),
                user=SimpleNamespace(name="alice", id=2),
                channel=SimpleNamespace(name="general", id=3),
                channel_id=3,
            ),
        )

    async def invoke_add(self, username: str) -> None:
        callback = cast(Any, self.cog.add_user).callback
        await callback(self.cog, self.interaction, username)

    def patch_report_destination(self, channel: object) -> mock.AsyncMock:
        """Patch channel lookup and sending; returns the send mock."""
        self.enterContext(
            patch(
                "ctfbot.features.alpacahack.cog.resolve_messageable",
                new_callable=mock.AsyncMock,
                return_value=channel,
            )
        )
        return self.enterContext(
            patch(
                "ctfbot.features.alpacahack.cog.send_safely",
                new_callable=mock.AsyncMock,
            )
        )

    async def test_daily_report_sends_only_after_new_challenge_is_reserved(
        self,
    ) -> None:
        self.client.fetch_daily_challenge.return_value = make_challenge()
        channel = Mock()
        send_safely = self.patch_report_destination(channel)

        await cast(Any, self.cog.daily_challenge_report).coro(self.cog)
        await cast(Any, self.cog.daily_challenge_report).coro(self.cog)

        send_safely.assert_awaited_once()
        self.assertEqual(send_safely.await_args_list[-1].args, (channel,))
        self.assertEqual(
            send_safely.await_args_list[-1].kwargs["content"], "🦙 Daily AlpacaHack"
        )

    async def test_daily_report_mentions_configured_target(self) -> None:
        role = Mock(spec=discord.Role)
        role.mention = "<@&20>"
        member = Mock(spec=discord.Member)
        member.mention = "<@30>"
        cases = (
            ("role", 20, role, None, "<@&20>", False, [role]),
            ("member", 30, None, member, "<@30>", [member], False),
            ("disabled", None, None, None, "", False, False),
        )
        for index, (
            name,
            mention_id,
            role_result,
            member_result,
            mention,
            users,
            roles,
        ) in enumerate(cases):
            with self.subTest(target=name):
                self.settings.alpacahack_mention_id = mention_id
                guild = Mock(spec=discord.Guild)
                guild.get_role.return_value = role_result
                guild.get_member.return_value = member_result
                self.bot.get_guild.return_value = guild
                self.client.fetch_daily_challenge.return_value = make_challenge(
                    f"https://alpacahack.com/daily/challenges/{index}"
                )
                send_safely = self.patch_report_destination(Mock())

                await cast(Any, self.cog.daily_challenge_report).coro(self.cog)

                kwargs = send_safely.await_args_list[-1].kwargs
                self.assertEqual(
                    kwargs["content"], f"{mention} 🦙 Daily AlpacaHack".lstrip()
                )
                self.assertEqual(kwargs["allowed_mentions"].users, users)
                self.assertEqual(kwargs["allowed_mentions"].roles, roles)

    async def test_daily_report_sends_without_mention_when_target_is_unresolvable(
        self,
    ) -> None:
        self.settings.alpacahack_mention_id = 99
        guild = Mock(spec=discord.Guild)
        guild.get_role.return_value = None
        guild.get_member.return_value = None
        guild.fetch_member = mock.AsyncMock(
            side_effect=discord.NotFound(Mock(status=404, reason="x"), "missing")
        )
        self.bot.get_guild.return_value = guild
        self.client.fetch_daily_challenge.return_value = make_challenge()
        send_safely = self.patch_report_destination(Mock())

        with self.assertLogs("ctfbot", level="WARNING"):
            await cast(Any, self.cog.daily_challenge_report).coro(self.cog)

        kwargs = send_safely.await_args_list[-1].kwargs
        self.assertEqual(kwargs["content"], "🦙 Daily AlpacaHack")
        self.assertFalse(kwargs["allowed_mentions"].users)
        self.assertFalse(kwargs["allowed_mentions"].roles)

    async def weekly_report(self, *, weekday_date: datetime.datetime) -> mock.AsyncMock:
        """Run the weekly report as if `weekday_date` were now."""
        send_safely = self.patch_report_destination(
            SimpleNamespace(name="alpaca", id=3)
        )
        # Replace only the cog module's `datetime`, not the stdlib class.
        clock = SimpleNamespace(datetime=SimpleNamespace(now=lambda tz: weekday_date))
        with (
            patch("ctfbot.features.alpacahack.cog.datetime", clock),
            patch("ctfbot.features.alpacahack.service.time"),
        ):
            await cast(Any, self.cog.weekly_solve_report).coro(self.cog)
        return send_safely

    SUNDAY = datetime.datetime(2026, 6, 21, tzinfo=datetime.UTC)

    async def test_weekly_report_logs_partial_failure_as_warning(self) -> None:
        self.db.add_alpacahack_user("alice", max_users=50)
        self.db.add_alpacahack_user("bob", max_users=50)
        self.client.fetch_solve_records.side_effect = [
            ExternalAPIError("failed"),
            [],
        ]

        with self.assertLogs("ctfbot", level="WARNING") as logs:
            send_safely = await self.weekly_report(weekday_date=self.SUNDAY)

        send_safely.assert_awaited_once()
        embed = send_safely.await_args_list[-1].kwargs["embed"]
        self.assertIn("取得失敗 1人", embed.description)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].levelno, logging.WARNING)
        self.assertIn("users=2 failed_users=1", logs.records[0].getMessage())

    async def test_weekly_report_without_failures_does_not_warn(self) -> None:
        self.db.add_alpacahack_user("alice", max_users=50)
        self.client.fetch_solve_records.return_value = []

        with self.assertNoLogs("ctfbot", level="WARNING"):
            send_safely = await self.weekly_report(weekday_date=self.SUNDAY)

        send_safely.assert_awaited_once()

    async def test_weekly_report_is_skipped_except_on_sunday(self) -> None:
        self.db.add_alpacahack_user("alice", max_users=50)

        send_safely = await self.weekly_report(
            weekday_date=datetime.datetime(2026, 6, 20, tzinfo=datetime.UTC)
        )

        send_safely.assert_not_awaited()
        self.client.fetch_solve_records.assert_not_called()

    async def test_daily_command_displays_current_challenge_without_reserving(
        self,
    ) -> None:
        challenge = make_challenge()
        self.client.fetch_daily_challenge.return_value = challenge

        await cast(Any, self.cog.show_daily).callback(self.cog, self.interaction)

        self.defer.assert_awaited_once()
        self.followup_send.assert_awaited_once_with(embed=_build_daily_embed(challenge))
        self.assertTrue(self.db.reserve_alpacahack_daily_notification(challenge.url))

    async def test_daily_command_reports_when_no_challenge_is_active(self) -> None:
        self.client.fetch_daily_challenge.return_value = None

        await cast(Any, self.cog.show_daily).callback(self.cog, self.interaction)

        self.send_interaction.assert_awaited_once_with(
            self.interaction,
            "公開中の Daily AlpacaHack 問題はありません。",
            ephemeral=False,
        )

    async def test_daily_command_reports_fetch_failure(self) -> None:
        self.client.fetch_daily_challenge.side_effect = ExternalAPIError("failed")

        with self.assertLogs("ctfbot", level="WARNING"):
            await cast(Any, self.cog.show_daily).callback(self.cog, self.interaction)

        self.send_interaction.assert_awaited_once_with(
            self.interaction,
            "AlpacaHack からの取得に失敗しました。",
            ephemeral=False,
        )

    async def test_add_rejects_too_long_and_invalid_usernames(self) -> None:
        for name in ("a" * 33, "invalid/name", "日本語"):
            with self.subTest(name=name):
                self.send_interaction.reset_mock()

                await self.invoke_add(name)

                self.send_interaction.assert_awaited_once_with(
                    self.interaction,
                    "ユーザー名は 32 文字以内の英数字と `-` `_` で入力してください。",
                )
        self.assertEqual(self.db.list_alpacahack_users(), [])

    async def test_add_accepts_32_character_username_with_dash_and_underscore(
        self,
    ) -> None:
        name = "a" * 29 + "-_x"

        await self.invoke_add(name)

        self.assertEqual(self.db.list_alpacahack_users(), [name])
        self.send_interaction.assert_awaited_once_with(
            self.interaction, f"`{name}` を登録しました。"
        )
        self.log_audit.assert_awaited_once()

    async def test_add_rejects_new_user_when_registration_limit_is_reached(
        self,
    ) -> None:
        for index in range(50):
            self.db.add_alpacahack_user(f"user{index}", max_users=50)

        await self.invoke_add("new_user")

        self.send_interaction.assert_awaited_once_with(
            self.interaction, "登録数が上限(50人)に達しています。"
        )
        self.assertNotIn("new_user", self.db.list_alpacahack_users())
        self.log_audit.assert_not_awaited()

    async def test_add_reports_already_registered_user(self) -> None:
        self.db.add_alpacahack_user("alice", max_users=50)

        await self.invoke_add("alice")

        self.send_interaction.assert_awaited_once_with(
            self.interaction, "`alice` は既に登録されています。"
        )
        self.assertEqual(self.db.list_alpacahack_users(), ["alice"])
        self.log_audit.assert_not_awaited()
