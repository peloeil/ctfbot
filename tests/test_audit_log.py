import datetime
import json
import unittest
from types import SimpleNamespace
from typing import cast
from unittest import mock

import discord
from discord.ext import commands

from bot.errors import RepositoryError
from bot.features.audit_log import AuditLog
from bot.runtime import BotRuntime


class StringValue:
    def __str__(self) -> str:
        return "string value"


class UnserializableValue:
    def __str__(self) -> str:
        raise ValueError("cannot stringify")


class AuditLogTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = mock.Mock()
        bot = cast(
            commands.Bot,
            SimpleNamespace(runtime=BotRuntime(settings=mock.Mock(), db=self.db)),
        )
        self.cog = AuditLog(bot)

    @staticmethod
    def make_entry(before_object: object | None = None) -> discord.AuditLogEntry:
        if before_object is None:
            before_object = StringValue()
        return cast(
            discord.AuditLogEntry,
            SimpleNamespace(
                id=100,
                guild=SimpleNamespace(id=200),
                action=SimpleNamespace(name="member_ban_add"),
                user_id=None,
                target=SimpleNamespace(id=300),
                reason="理由",
                changes=SimpleNamespace(
                    before={"name": "以前", "object": before_object},
                    after={"name": "以後"},
                ),
                extra=StringValue(),
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
