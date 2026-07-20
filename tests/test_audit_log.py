import datetime
import json
import unittest
from types import SimpleNamespace
from typing import cast
from unittest import mock

import discord
from discord.ext import commands

from bot.config import Settings
from bot.errors import RepositoryError
from bot.features.audit_log import AuditLog
from bot.runtime import BotRuntime


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


class AuditLogTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = mock.Mock()
        self.settings = mock.Mock(spec=Settings)
        self.settings.admin_role_id = 10
        self.settings.bot_channel_id = 20
        self.bot = cast(
            commands.Bot,
            SimpleNamespace(
                runtime=BotRuntime(settings=cast(Settings, self.settings), db=self.db)
            ),
        )
        self.cog = AuditLog(self.bot)

    @staticmethod
    def make_entry(
        before_object: object | None = None,
        *,
        user_id: int | None = None,
        target_id: int | None = 300,
        target_type: str | None = "user",
        target_name: str | None = None,
        reason: str | None = "理由",
        changes: object | None = None,
        extra: object | None = None,
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
                id=100,
                guild=SimpleNamespace(id=200),
                action=SimpleNamespace(name="member_ban_add", target_type=target_type),
                user_id=user_id,
                target=target,
                reason=reason,
                changes=changes,
                extra=StringValue() if extra is None else extra,
                created_at=datetime.datetime(2026, 7, 6, tzinfo=datetime.UTC),
            ),
        )

    async def test_event_serializes_and_inserts_entry(self) -> None:
        entry = self.make_entry()
        with mock.patch(
            "bot.features.audit_log.asyncio.to_thread", new_callable=mock.AsyncMock
        ) as to_thread:
            await self.cog.on_audit_log_entry_create(entry)

        to_thread.assert_awaited_once_with(
            self.db.insert_audit_log_entry,
            entry_id=100,
            guild_id=200,
            action="member_ban_add",
            user_id=None,
            target_id=300,
            reason="理由",
            changes_json=json.dumps(
                {
                    "before": {"name": "以前", "object": "string value"},
                    "after": {"name": "以後"},
                },
                ensure_ascii=False,
            ),
            extra_text="string value",
            created_at_unix=int(entry.created_at.timestamp()),
        )

    async def test_repository_error_is_logged_and_suppressed(self) -> None:
        entry = self.make_entry()
        error = RepositoryError("database unavailable")
        with (
            mock.patch(
                "bot.features.audit_log.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                side_effect=error,
            ),
            mock.patch("bot.features.audit_log.logger.error") as log_error,
        ):
            await self.cog.on_audit_log_entry_create(entry)

        log_error.assert_called_once_with(
            "Failed to save audit log entry %s: %s", entry.id, error
        )

    async def test_new_admin_entry_notifies_with_target_and_reason(self) -> None:
        entry = self.make_entry(user_id=400)
        member = SimpleNamespace(roles=[SimpleNamespace(id=10)])
        with (
            mock.patch(
                "bot.features.audit_log.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                return_value=True,
            ),
            mock.patch(
                "bot.features.audit_log.fetch_member",
                new_callable=mock.AsyncMock,
                return_value=member,
            ) as fetch_member,
            mock.patch(
                "bot.features.audit_log.send_audit_message",
                new_callable=mock.AsyncMock,
            ) as send_audit_message,
        ):
            await self.cog.on_audit_log_entry_create(entry)

        fetch_member.assert_awaited_once_with(entry.guild, 400)
        send_audit_message.assert_awaited_once_with(
            self.bot,
            [
                "🛡️ <@400> が管理者操作 `member_ban_add` を実行しました。",
                "- 対象: <@300>",
                "- 理由: 理由",
            ],
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
        member = SimpleNamespace(roles=[SimpleNamespace(id=10)])
        for target_type, expected in cases:
            with self.subTest(target_type=target_type):
                entry = self.make_entry(user_id=400, target_type=target_type)
                with (
                    mock.patch(
                        "bot.features.audit_log.asyncio.to_thread",
                        new_callable=mock.AsyncMock,
                        return_value=True,
                    ),
                    mock.patch(
                        "bot.features.audit_log.fetch_member",
                        new_callable=mock.AsyncMock,
                        return_value=member,
                    ),
                    mock.patch(
                        "bot.features.audit_log.send_audit_message",
                        new_callable=mock.AsyncMock,
                    ) as send_audit_message,
                ):
                    await self.cog.on_audit_log_entry_create(entry)

                call = send_audit_message.await_args
                assert call is not None
                self.assertEqual(call.args[1][1], expected)

    async def test_admin_entry_formats_target_name_when_not_mentionable(self) -> None:
        cases = [
            # emoji はキャッシュ済み target の name を :name: 形式で表示する
            (
                self.make_entry(
                    user_id=400, target_type="emoji", target_name="party_blob"
                ),
                "- 対象: :party_blob:",
            ),
            # 削除済みでも changes に残る name を表示し、sanitize を適用する
            (
                self.make_entry(
                    user_id=400,
                    target_type="sticker",
                    changes=SimpleNamespace(
                        before=DiffStub({"name": " <@1>  スタンプ "}),
                        after=DiffStub({}),
                    ),
                ),
                "- 対象: <@\u200b1> スタンプ",
            ),
        ]
        member = SimpleNamespace(roles=[SimpleNamespace(id=10)])
        for entry, expected in cases:
            with self.subTest(expected=expected):
                with (
                    mock.patch(
                        "bot.features.audit_log.asyncio.to_thread",
                        new_callable=mock.AsyncMock,
                        return_value=True,
                    ),
                    mock.patch(
                        "bot.features.audit_log.fetch_member",
                        new_callable=mock.AsyncMock,
                        return_value=member,
                    ),
                    mock.patch(
                        "bot.features.audit_log.send_audit_message",
                        new_callable=mock.AsyncMock,
                    ) as send_audit_message,
                ):
                    await self.cog.on_audit_log_entry_create(entry)

                call = send_audit_message.await_args
                assert call is not None
                self.assertEqual(call.args[1][1], expected)

    async def test_admin_pin_entry_appends_message_link(self) -> None:
        entry = self.make_entry(
            user_id=400,
            target_id=None,
            target_type="message",
            extra=SimpleNamespace(channel=SimpleNamespace(id=500), message_id=600),
        )
        member = SimpleNamespace(roles=[SimpleNamespace(id=10)])
        with (
            mock.patch(
                "bot.features.audit_log.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                return_value=True,
            ),
            mock.patch(
                "bot.features.audit_log.fetch_member",
                new_callable=mock.AsyncMock,
                return_value=member,
            ),
            mock.patch(
                "bot.features.audit_log.send_audit_message",
                new_callable=mock.AsyncMock,
            ) as send_audit_message,
        ):
            await self.cog.on_audit_log_entry_create(entry)

        send_audit_message.assert_awaited_once_with(
            self.bot,
            [
                "🛡️ <@400> が管理者操作 `member_ban_add` を実行しました。",
                "- メッセージ: https://discord.com/channels/200/500/600",
                "- 理由: 理由",
            ],
        )

    async def test_new_admin_entry_omits_missing_target_and_reason(self) -> None:
        entry = self.make_entry(user_id=400, target_id=None, reason=None)
        member = SimpleNamespace(roles=[SimpleNamespace(id=10)])
        with (
            mock.patch(
                "bot.features.audit_log.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                return_value=True,
            ),
            mock.patch(
                "bot.features.audit_log.fetch_member",
                new_callable=mock.AsyncMock,
                return_value=member,
            ),
            mock.patch(
                "bot.features.audit_log.send_audit_message",
                new_callable=mock.AsyncMock,
            ) as send_audit_message,
        ):
            await self.cog.on_audit_log_entry_create(entry)

        send_audit_message.assert_awaited_once_with(
            self.bot,
            ["🛡️ <@400> が管理者操作 `member_ban_add` を実行しました。"],
        )

    async def test_new_non_admin_entry_does_not_notify(self) -> None:
        entry = self.make_entry(user_id=400)
        member = SimpleNamespace(roles=[SimpleNamespace(id=11)])
        with (
            mock.patch(
                "bot.features.audit_log.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                return_value=True,
            ) as to_thread,
            mock.patch(
                "bot.features.audit_log.fetch_member",
                new_callable=mock.AsyncMock,
                return_value=member,
            ),
            mock.patch(
                "bot.features.audit_log.send_audit_message",
                new_callable=mock.AsyncMock,
            ) as send_audit_message,
        ):
            await self.cog.on_audit_log_entry_create(entry)

        to_thread.assert_awaited_once()
        send_audit_message.assert_not_awaited()

    async def test_entry_without_user_does_not_resolve_member_or_notify(self) -> None:
        entry = self.make_entry(user_id=None)
        with (
            mock.patch(
                "bot.features.audit_log.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                return_value=True,
            ) as to_thread,
            mock.patch(
                "bot.features.audit_log.fetch_member", new_callable=mock.AsyncMock
            ) as fetch_member,
            mock.patch(
                "bot.features.audit_log.send_audit_message",
                new_callable=mock.AsyncMock,
            ) as send_audit_message,
        ):
            await self.cog.on_audit_log_entry_create(entry)

        to_thread.assert_awaited_once()
        fetch_member.assert_not_awaited()
        send_audit_message.assert_not_awaited()

    async def test_entry_without_configured_admin_role_does_not_notify(self) -> None:
        self.settings.admin_role_id = None
        entry = self.make_entry(user_id=400)
        with (
            mock.patch(
                "bot.features.audit_log.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                return_value=True,
            ) as to_thread,
            mock.patch(
                "bot.features.audit_log.fetch_member", new_callable=mock.AsyncMock
            ) as fetch_member,
            mock.patch(
                "bot.features.audit_log.send_audit_message",
                new_callable=mock.AsyncMock,
            ) as send_audit_message,
        ):
            await self.cog.on_audit_log_entry_create(entry)

        to_thread.assert_awaited_once()
        fetch_member.assert_not_awaited()
        send_audit_message.assert_not_awaited()

    async def test_entry_with_unresolved_member_does_not_notify(self) -> None:
        entry = self.make_entry(user_id=400)
        with (
            mock.patch(
                "bot.features.audit_log.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                return_value=True,
            ) as to_thread,
            mock.patch(
                "bot.features.audit_log.fetch_member",
                new_callable=mock.AsyncMock,
                return_value=None,
            ),
            mock.patch(
                "bot.features.audit_log.send_audit_message",
                new_callable=mock.AsyncMock,
            ) as send_audit_message,
        ):
            await self.cog.on_audit_log_entry_create(entry)

        to_thread.assert_awaited_once()
        send_audit_message.assert_not_awaited()

    async def test_duplicate_entry_does_not_resolve_member_or_notify(self) -> None:
        entry = self.make_entry(user_id=400)
        with (
            mock.patch(
                "bot.features.audit_log.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                return_value=False,
            ) as to_thread,
            mock.patch(
                "bot.features.audit_log.fetch_member", new_callable=mock.AsyncMock
            ) as fetch_member,
            mock.patch(
                "bot.features.audit_log.send_audit_message",
                new_callable=mock.AsyncMock,
            ) as send_audit_message,
        ):
            await self.cog.on_audit_log_entry_create(entry)

        to_thread.assert_awaited_once()
        fetch_member.assert_not_awaited()
        send_audit_message.assert_not_awaited()

    async def test_repository_error_does_not_notify(self) -> None:
        entry = self.make_entry(user_id=400)
        error = RepositoryError("database unavailable")
        with (
            mock.patch(
                "bot.features.audit_log.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                side_effect=error,
            ),
            mock.patch(
                "bot.features.audit_log.send_audit_message",
                new_callable=mock.AsyncMock,
            ) as send_audit_message,
            mock.patch("bot.features.audit_log.logger.error") as log_error,
        ):
            await self.cog.on_audit_log_entry_create(entry)

        send_audit_message.assert_not_awaited()
        log_error.assert_called_once_with(
            "Failed to save audit log entry %s: %s", entry.id, error
        )

    async def test_admin_entry_sanitizes_reason_before_notification(self) -> None:
        entry = self.make_entry(user_id=400, reason="  <@123>\n  複数   空白  ")
        member = SimpleNamespace(roles=[SimpleNamespace(id=10)])
        with (
            mock.patch(
                "bot.features.audit_log.asyncio.to_thread",
                new_callable=mock.AsyncMock,
                return_value=True,
            ),
            mock.patch(
                "bot.features.audit_log.fetch_member",
                new_callable=mock.AsyncMock,
                return_value=member,
            ),
            mock.patch(
                "bot.features.audit_log.send_audit_message",
                new_callable=mock.AsyncMock,
            ) as send_audit_message,
        ):
            await self.cog.on_audit_log_entry_create(entry)

        call = send_audit_message.await_args
        assert call is not None
        self.assertEqual(call.args[1][-1], "- 理由: <@\u200b123> 複数 空白")

    async def test_event_with_unserializable_value_is_logged_and_suppressed(
        self,
    ) -> None:
        entry = self.make_entry(UnserializableValue())
        with mock.patch("bot.features.audit_log.logger.error") as log_error:
            await self.cog.on_audit_log_entry_create(entry)

        error = log_error.call_args.args[2]
        self.assertIsInstance(error, ValueError)
        log_error.assert_called_once_with(
            "Failed to save audit log entry %s: %s", entry.id, error
        )


if __name__ == "__main__":
    unittest.main()
