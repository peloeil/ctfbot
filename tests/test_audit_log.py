import datetime
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import suppress
from types import SimpleNamespace
from typing import cast
from unittest import mock

import discord
from discord.ext import commands

from ctfbot.config import Settings
from ctfbot.db import Database
from ctfbot.features.audit_log import AuditLog
from ctfbot.runtime import BotRuntime


class StringValue:
    def __str__(self) -> str:
        return "string value"


class UnserializableValue:
    def __str__(self) -> str:
        raise ValueError("cannot stringify")


class DiffStub(dict):
    """dict() 変換と属性アクセスの両方に応える AuditLogDiff の代役。"""

    def __getattr__(self, item: str) -> object:
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc


ADMIN_ROLE_ID = 10
BOT_CHANNEL_ID = 900


class AuditLogTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        fd, self.path = tempfile.mkstemp()
        os.close(fd)
        os.unlink(self.path)
        self.addCleanup(self.remove_database)
        self.db = Database(self.path)
        self.settings = mock.Mock(spec=Settings)
        self.settings.admin_role_id = ADMIN_ROLE_ID
        self.settings.bot_channel_id = BOT_CHANNEL_ID
        self.channel = mock.Mock(spec=discord.TextChannel)
        self.channel.send = mock.AsyncMock()
        self.bot = cast(
            commands.Bot,
            SimpleNamespace(
                runtime=BotRuntime(settings=cast(Settings, self.settings), db=self.db),
                get_channel=lambda channel_id: (
                    self.channel if channel_id == BOT_CHANNEL_ID else None
                ),
            ),
        )
        self.cog = AuditLog(self.bot)

    def remove_database(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            with suppress(FileNotFoundError):
                os.unlink(self.path + suffix)

    def rows(self) -> list[dict[str, object]]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            return [
                dict(row)
                for row in conn.execute("SELECT * FROM audit_log_entry ORDER BY id")
            ]
        finally:
            conn.close()

    @staticmethod
    def make_guild(member: object | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            id=200,
            get_member=lambda user_id: member,
            fetch_member=mock.AsyncMock(
                side_effect=discord.NotFound(
                    mock.Mock(status=404, reason="Not Found"), "unknown member"
                )
            ),
        )

    @staticmethod
    def admin_member() -> SimpleNamespace:
        return SimpleNamespace(roles=[SimpleNamespace(id=ADMIN_ROLE_ID)])

    @staticmethod
    def make_entry(
        before_object: object | None = None,
        *,
        entry_id: int = 100,
        user_id: int | None = None,
        target_id: int | None = 300,
        target_type: str | None = "user",
        target_name: str | None = None,
        reason: str | None = "理由",
        changes: object | None = None,
        extra: object | None = None,
        member: object | None = None,
    ) -> discord.AuditLogEntry:
        if before_object is None:
            before_object = StringValue()
        if target_name is not None:
            target = SimpleNamespace(id=target_id, name=target_name)
        else:
            target = SimpleNamespace(id=target_id)
        if changes is None:
            changes = SimpleNamespace(
                before={"name": "以前", "object": before_object},
                after={"name": "以後"},
            )
        return cast(
            discord.AuditLogEntry,
            SimpleNamespace(
                id=entry_id,
                guild=AuditLogTest.make_guild(member),
                action=SimpleNamespace(name="member_ban_add", target_type=target_type),
                user_id=user_id,
                target=target,
                reason=reason,
                changes=changes,
                extra=StringValue() if extra is None else extra,
                created_at=datetime.datetime(2026, 7, 6, tzinfo=datetime.UTC),
            ),
        )

    def sent_lines(self) -> list[str]:
        self.channel.send.assert_awaited_once()
        return self.channel.send.await_args.args[0].split("\n")

    async def test_event_stores_entry_with_serialized_changes(self) -> None:
        entry = self.make_entry()
        await self.cog.on_audit_log_entry_create(entry)

        (row,) = self.rows()
        changes_json = cast(str, row.pop("changes_json"))
        self.assertEqual(
            json.loads(changes_json),
            {
                "before": {"name": "以前", "object": "string value"},
                "after": {"name": "以後"},
            },
        )
        self.assertEqual(
            row,
            {
                "id": 1,
                "entry_id": 100,
                "guild_id": 200,
                "action": "member_ban_add",
                "user_id": None,
                "target_id": 300,
                "reason": "理由",
                "extra_text": "string value",
                "created_at_unix": int(entry.created_at.timestamp()),
            },
        )

    async def test_new_admin_entry_notifies_with_target_and_reason(self) -> None:
        entry = self.make_entry(user_id=400, member=self.admin_member())
        await self.cog.on_audit_log_entry_create(entry)

        self.assertEqual(
            self.sent_lines(),
            [
                "🛡️ <@400> が管理者操作 `member_ban_add` を実行しました。",
                "- 対象: <@300>",
                "- 理由: 理由",
            ],
        )

    async def test_notification_does_not_ping_anyone(self) -> None:
        await self.cog.on_audit_log_entry_create(
            self.make_entry(user_id=400, member=self.admin_member())
        )

        allowed_mentions = self.channel.send.await_args.kwargs["allowed_mentions"]
        self.assertEqual(
            allowed_mentions.to_dict(), discord.AllowedMentions.none().to_dict()
        )

    async def test_admin_entry_formats_target_by_target_type(self) -> None:
        cases = [
            ("channel", "- 対象: <#300>"),
            ("thread", "- 対象: <#300>"),
            ("role", "- 対象: <@&300>"),
            ("message", "- 対象: <@300>"),
            ("sticker", "- 対象 ID: 300"),
            (None, "- 対象 ID: 300"),
        ]
        for index, (target_type, expected) in enumerate(cases):
            with self.subTest(target_type=target_type):
                self.channel.send.reset_mock()
                entry = self.make_entry(
                    entry_id=index,
                    user_id=400,
                    target_type=target_type,
                    member=self.admin_member(),
                )
                await self.cog.on_audit_log_entry_create(entry)

                self.assertEqual(self.sent_lines()[1], expected)

    async def test_admin_entry_formats_target_name_when_not_mentionable(self) -> None:
        member = self.admin_member()
        cases = [
            # emoji はキャッシュ済み target の name を :name: 形式で表示する
            (
                self.make_entry(
                    entry_id=1,
                    user_id=400,
                    target_type="emoji",
                    target_name="party_blob",
                    member=member,
                ),
                "- 対象: :party_blob:",
            ),
            # 削除済みでも changes に残る name を表示し、sanitize を適用する
            (
                self.make_entry(
                    entry_id=2,
                    user_id=400,
                    target_type="sticker",
                    changes=SimpleNamespace(
                        before=DiffStub({"name": " <@1>  スタンプ "}),
                        after=DiffStub({}),
                    ),
                    member=member,
                ),
                "- 対象: <@\u200b1> スタンプ",
            ),
        ]
        for entry, expected in cases:
            with self.subTest(expected=expected):
                self.channel.send.reset_mock()
                await self.cog.on_audit_log_entry_create(entry)

                self.assertEqual(self.sent_lines()[1], expected)

    async def test_admin_pin_entry_appends_message_link(self) -> None:
        entry = self.make_entry(
            user_id=400,
            target_id=None,
            target_type="message",
            extra=SimpleNamespace(channel=SimpleNamespace(id=500), message_id=600),
            member=self.admin_member(),
        )
        await self.cog.on_audit_log_entry_create(entry)

        self.assertEqual(
            self.sent_lines(),
            [
                "🛡️ <@400> が管理者操作 `member_ban_add` を実行しました。",
                "- メッセージ: https://discord.com/channels/200/500/600",
                "- 理由: 理由",
            ],
        )

    async def test_new_admin_entry_omits_missing_target_and_reason(self) -> None:
        entry = self.make_entry(
            user_id=400, target_id=None, reason=None, member=self.admin_member()
        )
        await self.cog.on_audit_log_entry_create(entry)

        self.assertEqual(
            self.sent_lines(),
            ["🛡️ <@400> が管理者操作 `member_ban_add` を実行しました。"],
        )

    async def test_new_non_admin_entry_is_stored_without_notification(self) -> None:
        member = SimpleNamespace(roles=[SimpleNamespace(id=11)])
        await self.cog.on_audit_log_entry_create(
            self.make_entry(user_id=400, member=member)
        )

        self.assertEqual(len(self.rows()), 1)
        self.channel.send.assert_not_awaited()

    async def test_entry_without_user_is_stored_without_notification(self) -> None:
        await self.cog.on_audit_log_entry_create(self.make_entry(user_id=None))

        self.assertEqual(len(self.rows()), 1)
        self.channel.send.assert_not_awaited()

    async def test_entry_without_configured_admin_role_does_not_notify(self) -> None:
        self.settings.admin_role_id = None
        await self.cog.on_audit_log_entry_create(
            self.make_entry(user_id=400, member=self.admin_member())
        )

        self.assertEqual(len(self.rows()), 1)
        self.channel.send.assert_not_awaited()

    async def test_entry_with_unresolved_member_does_not_notify(self) -> None:
        await self.cog.on_audit_log_entry_create(self.make_entry(user_id=400))

        self.assertEqual(len(self.rows()), 1)
        self.channel.send.assert_not_awaited()

    async def test_duplicate_entry_is_stored_once_and_notified_once(self) -> None:
        for _ in range(2):
            await self.cog.on_audit_log_entry_create(
                self.make_entry(user_id=400, member=self.admin_member())
            )

        self.assertEqual(len(self.rows()), 1)
        self.channel.send.assert_awaited_once()

    async def test_repository_error_is_logged_and_does_not_notify(self) -> None:
        conn = sqlite3.connect(self.path)
        conn.execute("DROP TABLE audit_log_entry")
        conn.close()

        with self.assertLogs("ctfbot", level="ERROR") as logs:
            await self.cog.on_audit_log_entry_create(
                self.make_entry(user_id=400, member=self.admin_member())
            )

        self.assertIn("Failed to save audit log entry 100", logs.output[0])
        self.channel.send.assert_not_awaited()

    async def test_admin_entry_sanitizes_reason_before_notification(self) -> None:
        entry = self.make_entry(
            user_id=400, reason="  <@123>\n  複数   空白  ", member=self.admin_member()
        )
        await self.cog.on_audit_log_entry_create(entry)

        self.assertEqual(self.sent_lines()[-1], "- 理由: <@\u200b123> 複数 空白")

    async def test_event_with_unserializable_value_is_logged_and_suppressed(
        self,
    ) -> None:
        entry = self.make_entry(UnserializableValue(), user_id=400)
        with self.assertLogs("ctfbot", level="ERROR") as logs:
            await self.cog.on_audit_log_entry_create(entry)

        self.assertIn("Failed to save audit log entry 100", logs.output[0])
        self.assertIn("cannot stringify", logs.output[0])
        self.assertEqual(self.rows(), [])
        self.channel.send.assert_not_awaited()
