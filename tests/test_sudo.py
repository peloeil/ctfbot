import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import discord
from discord.ext import commands, tasks

from ctfbot.db import Database
from ctfbot.features.sudo.cog import ROLE_ADD_ERROR, ROLE_REMOVE_ERROR, Sudo
from ctfbot.features.sudo.models import SudoGrant
from ctfbot.runtime import BotRuntime

USER_ID = 2
ADMIN_ROLE_ID = 10
SUDOER_ROLE_ID = 20
SUDO_DURATION_SECONDS = 30 * 60
NOW = 100
EXPIRES_AT = NOW + SUDO_DURATION_SECONDS


def forbidden() -> discord.Forbidden:
    return discord.Forbidden(mock.Mock(status=403, reason="Forbidden"), "denied")


def not_found() -> discord.NotFound:
    return discord.NotFound(mock.Mock(status=404, reason="Not Found"), "missing")


class SudoTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database(str(Path(tmp.name) / "test.db"))
        self.bot = mock.Mock(spec=commands.Bot)
        self.bot.runtime = BotRuntime(
            settings=cast(
                Any,
                SimpleNamespace(
                    guild_id=1,
                    admin_role_id=ADMIN_ROLE_ID,
                    sudoer_role_id=SUDOER_ROLE_ID,
                    sudo_duration_minutes=30,
                    bot_channel_id=30,
                ),
            ),
            db=self.db,
        )
        # The cog starts its expiry loop on construction; it is driven by hand here.
        with mock.patch.object(tasks.Loop, "start"):
            self.cog = Sudo(self.bot)

        # Replace only the cog module's `time`, not the process-wide clock.
        self.clock = mock.Mock()
        self.clock.time.return_value = NOW
        self.enterContext(mock.patch("ctfbot.features.sudo.cog.time", self.clock))
        self.send_interaction = self.enterContext(
            mock.patch(
                "ctfbot.features.sudo.cog.send_interaction",
                new_callable=mock.AsyncMock,
            )
        )
        self.log_audit = self.enterContext(
            mock.patch(
                "ctfbot.features.sudo.cog.log_audit", new_callable=mock.AsyncMock
            )
        )

    @staticmethod
    def make_interaction(
        *,
        member_roles: list[mock.Mock] | None = None,
        configured_role: mock.Mock | None = None,
    ) -> tuple[discord.Interaction, mock.Mock, mock.Mock, mock.Mock]:
        sudoer_role = mock.Mock(spec=discord.Role, id=SUDOER_ROLE_ID)
        role = configured_role or mock.Mock(spec=discord.Role, id=ADMIN_ROLE_ID)
        member = mock.Mock(spec=discord.Member, id=USER_ID, display_name="alice")
        member.roles = member_roles if member_roles is not None else [sudoer_role]
        member.add_roles = mock.AsyncMock()
        member.remove_roles = mock.AsyncMock()
        guild = mock.Mock(spec=discord.Guild, id=1)
        guild.get_role.return_value = role
        interaction = cast(
            discord.Interaction,
            SimpleNamespace(guild=guild, user=member),
        )
        return interaction, guild, member, role

    async def run_sudo(self, interaction: discord.Interaction) -> None:
        await cast(Any, self.cog.sudo).callback(self.cog, interaction)

    async def run_unsudo(self, interaction: discord.Interaction) -> None:
        await cast(Any, self.cog.unsudo).callback(self.cog, interaction)

    async def run_expiry_check(self, *, now: int) -> None:
        self.clock.time.return_value = now
        await cast(Any, self.cog.revoke_expired_grants).coro(self.cog)

    def expiry_fixtures(
        self,
    ) -> tuple[mock.Mock, mock.Mock, mock.Mock, mock.AsyncMock, mock.AsyncMock]:
        """Guild/member/role plus patched channel lookup and notification."""
        _, guild, member, role = self.make_interaction()
        guild.get_member.return_value = member
        self.bot.get_guild.return_value = guild
        channel = mock.Mock()
        resolve = self.enterContext(
            mock.patch(
                "ctfbot.features.sudo.cog.resolve_messageable",
                new_callable=mock.AsyncMock,
                return_value=channel,
            )
        )
        send_safely = self.enterContext(
            mock.patch(
                "ctfbot.features.sudo.cog.send_safely", new_callable=mock.AsyncMock
            )
        )
        return guild, member, role, resolve, send_safely

    async def test_sudo_rejects_member_without_sudoer_role(self) -> None:
        interaction, _, member, _ = self.make_interaction(member_roles=[])

        await self.run_sudo(interaction)

        self.send_interaction.assert_awaited_once_with(
            interaction, "このコマンドを実行するには sudoer ロールが必要です。"
        )
        self.assertIsNone(self.db.get_sudo_grant(USER_ID))
        member.add_roles.assert_not_awaited()

    async def test_sudo_does_not_convert_permanent_role_to_grant(self) -> None:
        admin_role = mock.Mock(spec=discord.Role, id=ADMIN_ROLE_ID)
        sudoer_role = mock.Mock(spec=discord.Role, id=SUDOER_ROLE_ID)
        interaction, _, member, _ = self.make_interaction(
            member_roles=[sudoer_role, admin_role], configured_role=admin_role
        )

        await self.run_sudo(interaction)

        self.send_interaction.assert_awaited_once_with(
            interaction, "既に管理者ロールを保持しています。"
        )
        self.assertIsNone(self.db.get_sudo_grant(USER_ID))
        member.add_roles.assert_not_awaited()

    async def test_sudo_records_grant_before_adding_role(self) -> None:
        interaction, _, member, role = self.make_interaction()
        grant_seen_by_discord: list[SudoGrant | None] = []

        async def add_role(_role: discord.Role) -> None:
            grant_seen_by_discord.append(self.db.get_sudo_grant(USER_ID))

        member.add_roles.side_effect = add_role

        await self.run_sudo(interaction)

        expected = SudoGrant(USER_ID, ADMIN_ROLE_ID, NOW, EXPIRES_AT)
        self.assertEqual(grant_seen_by_discord, [expected])
        self.assertEqual(self.db.get_sudo_grant(USER_ID), expected)
        member.add_roles.assert_awaited_once_with(role)
        self.send_interaction.assert_awaited_once_with(
            interaction,
            f"⏫ 管理者ロールを付与しました。<t:{EXPIRES_AT}:R> に自動解除されます。",
        )
        self.log_audit.assert_awaited_once()

    async def test_sudo_deletes_grant_when_role_assignment_fails(self) -> None:
        interaction, _, member, _ = self.make_interaction()
        member.add_roles.side_effect = forbidden()

        await self.run_sudo(interaction)

        self.assertIsNone(self.db.get_sudo_grant(USER_ID))
        self.send_interaction.assert_awaited_once_with(interaction, ROLE_ADD_ERROR)
        self.log_audit.assert_not_awaited()

    async def test_sudo_renewal_uses_saved_role_whatever_the_configured_role(
        self,
    ) -> None:
        granted_role = mock.Mock(spec=discord.Role, id=9)
        sudoer_role = mock.Mock(spec=discord.Role, id=SUDOER_ROLE_ID)
        other_configured = mock.Mock(spec=discord.Role, id=ADMIN_ROLE_ID)
        for name, configured in (("changed", other_configured), ("missing", None)):
            with self.subTest(configured_role=name):
                self.db.upsert_sudo_grant(USER_ID, 9, 50, 200)
                self.send_interaction.reset_mock()
                interaction, guild, member, _ = self.make_interaction(
                    member_roles=[sudoer_role, granted_role]
                )
                guild.get_role.side_effect = {
                    9: granted_role,
                    ADMIN_ROLE_ID: configured,
                }.get

                await self.run_sudo(interaction)

                self.assertEqual(
                    self.db.get_sudo_grant(USER_ID),
                    SudoGrant(USER_ID, 9, 50, EXPIRES_AT),
                )
                member.add_roles.assert_not_awaited()
                self.send_interaction.assert_awaited_once_with(
                    interaction, f"⏫ 有効期限を <t:{EXPIRES_AT}:R> に延長しました。"
                )

    async def test_sudo_grants_configured_role_when_saved_role_was_deleted(
        self,
    ) -> None:
        self.db.upsert_sudo_grant(USER_ID, 9, 50, 200)
        interaction, guild, member, role = self.make_interaction()
        guild.get_role.side_effect = {9: None, ADMIN_ROLE_ID: role}.get

        await self.run_sudo(interaction)

        self.assertEqual(
            self.db.get_sudo_grant(USER_ID),
            SudoGrant(USER_ID, ADMIN_ROLE_ID, NOW, EXPIRES_AT),
        )
        member.add_roles.assert_awaited_once_with(role)
        self.send_interaction.assert_awaited_once_with(
            interaction,
            f"⏫ 管理者ロールを付与しました。<t:{EXPIRES_AT}:R> に自動解除されます。",
        )

    async def test_sudo_without_grant_rejects_missing_configured_role(self) -> None:
        interaction, guild, _, _ = self.make_interaction()
        guild.get_role.return_value = None

        await self.run_sudo(interaction)

        self.send_interaction.assert_awaited_once_with(
            interaction, "付与対象のロールが見つかりません。"
        )
        self.assertIsNone(self.db.get_sudo_grant(USER_ID))

    async def test_sudo_failed_renewal_restores_previous_grant(self) -> None:
        previous = self.db.upsert_sudo_grant(USER_ID, ADMIN_ROLE_ID, 50, 200)
        interaction, _, member, _ = self.make_interaction()
        member.add_roles.side_effect = forbidden()

        await self.run_sudo(interaction)

        self.assertEqual(self.db.get_sudo_grant(USER_ID), previous)
        self.send_interaction.assert_awaited_once_with(interaction, ROLE_ADD_ERROR)

    async def test_unsudo_removes_role_and_grant(self) -> None:
        self.db.upsert_sudo_grant(USER_ID, ADMIN_ROLE_ID, 50, 200)
        interaction, _, member, role = self.make_interaction()

        await self.run_unsudo(interaction)

        member.remove_roles.assert_awaited_once_with(role)
        self.assertIsNone(self.db.get_sudo_grant(USER_ID))
        self.send_interaction.assert_awaited_once_with(
            interaction, "⏬ 管理者ロールを解除しました。"
        )
        self.log_audit.assert_awaited_once()

    async def test_unsudo_without_grant_reports_not_elevated(self) -> None:
        interaction, _, member, _ = self.make_interaction()

        await self.run_unsudo(interaction)

        self.send_interaction.assert_awaited_once_with(
            interaction, "昇格中ではありません。"
        )
        member.remove_roles.assert_not_awaited()
        self.log_audit.assert_not_awaited()

    async def test_unsudo_keeps_grant_when_role_removal_fails(self) -> None:
        previous = self.db.upsert_sudo_grant(USER_ID, ADMIN_ROLE_ID, 100, 200)
        interaction, _, member, _ = self.make_interaction()
        member.remove_roles.side_effect = forbidden()

        await self.run_unsudo(interaction)

        self.assertEqual(self.db.get_sudo_grant(USER_ID), previous)
        self.send_interaction.assert_awaited_once_with(interaction, ROLE_REMOVE_ERROR)

    async def test_expired_grant_removes_role_then_record_and_notifies(self) -> None:
        self.db.upsert_sudo_grant(USER_ID, ADMIN_ROLE_ID, 100, 200)
        _, member, role, resolve, send_safely = self.expiry_fixtures()
        grant_seen_at_removal: list[SudoGrant | None] = []

        async def remove_role(_role: discord.Role) -> None:
            grant_seen_at_removal.append(self.db.get_sudo_grant(USER_ID))

        member.remove_roles.side_effect = remove_role

        await self.run_expiry_check(now=300)

        self.assertEqual(
            grant_seen_at_removal, [SudoGrant(USER_ID, ADMIN_ROLE_ID, 100, 200)]
        )
        self.assertIsNone(self.db.get_sudo_grant(USER_ID))
        member.remove_roles.assert_awaited_once_with(role)
        channel, text = send_safely.await_args_list[-1].args[:2]
        self.assertIs(channel, resolve.return_value)
        self.assertEqual(text, "⏬ <@2> の管理者ロールを自動解除しました。")

    async def test_expired_grant_with_deleted_role_is_dropped_and_notified(
        self,
    ) -> None:
        self.db.upsert_sudo_grant(USER_ID, ADMIN_ROLE_ID, 100, 200)
        guild, member, _, _, send_safely = self.expiry_fixtures()
        guild.get_role.return_value = None

        await self.run_expiry_check(now=300)

        self.assertIsNone(self.db.get_sudo_grant(USER_ID))
        member.remove_roles.assert_not_awaited()
        send_safely.assert_awaited_once()

    async def test_unexpired_grant_is_left_untouched(self) -> None:
        grant = self.db.upsert_sudo_grant(USER_ID, ADMIN_ROLE_ID, 100, 200)
        _, member, _, _, send_safely = self.expiry_fixtures()

        await self.run_expiry_check(now=199)

        self.assertEqual(self.db.get_sudo_grant(USER_ID), grant)
        member.remove_roles.assert_not_awaited()
        send_safely.assert_not_awaited()

    async def test_expired_grant_for_departed_member_deletes_only_record(self) -> None:
        self.db.upsert_sudo_grant(USER_ID, ADMIN_ROLE_ID, 100, 200)
        guild, _, _, _, send_safely = self.expiry_fixtures()
        guild.get_member.return_value = None
        guild.fetch_member = mock.AsyncMock(side_effect=not_found())

        await self.run_expiry_check(now=300)

        self.assertIsNone(self.db.get_sudo_grant(USER_ID))
        send_safely.assert_not_awaited()

    async def test_expired_grant_keeps_record_when_member_lookup_fails(self) -> None:
        grant = self.db.upsert_sudo_grant(USER_ID, ADMIN_ROLE_ID, 100, 200)
        guild, _, _, _, send_safely = self.expiry_fixtures()
        guild.get_member.return_value = None
        guild.fetch_member = mock.AsyncMock(side_effect=forbidden())

        await self.run_expiry_check(now=300)

        self.assertEqual(self.db.get_sudo_grant(USER_ID), grant)
        send_safely.assert_not_awaited()

    async def test_expired_grant_keeps_record_when_role_removal_is_forbidden(
        self,
    ) -> None:
        grant = self.db.upsert_sudo_grant(USER_ID, ADMIN_ROLE_ID, 100, 200)
        _, member, _, _, send_safely = self.expiry_fixtures()
        member.remove_roles.side_effect = forbidden()

        with self.assertLogs("ctfbot", level="WARNING"):
            await self.run_expiry_check(now=300)

        self.assertEqual(self.db.get_sudo_grant(USER_ID), grant)
        send_safely.assert_not_awaited()

    async def test_expired_snapshot_does_not_revoke_renewed_grant(self) -> None:
        stale = SudoGrant(USER_ID, ADMIN_ROLE_ID, 100, 200)
        renewed = self.db.upsert_sudo_grant(USER_ID, ADMIN_ROLE_ID, 100, 1900)
        _, member, _, _, send_safely = self.expiry_fixtures()

        with mock.patch.object(
            self.db, "list_expired_sudo_grants", return_value=[stale]
        ):
            await self.run_expiry_check(now=300)

        self.assertEqual(self.db.get_sudo_grant(USER_ID), renewed)
        member.remove_roles.assert_not_awaited()
        send_safely.assert_not_awaited()

    async def test_unsudo_waits_for_in_flight_sudo_transition(self) -> None:
        interaction, _, member, _ = self.make_interaction()
        role_add_started = asyncio.Event()
        release_role_add = asyncio.Event()
        calls: list[str] = []

        async def add_role(*args) -> None:
            calls.append("add-start")
            role_add_started.set()
            await release_role_add.wait()
            calls.append("add-end")

        async def remove_role(*args) -> None:
            calls.append("remove")

        member.add_roles.side_effect = add_role
        member.remove_roles.side_effect = remove_role

        sudo_task = asyncio.create_task(self.run_sudo(interaction))
        await role_add_started.wait()
        unsudo_task = asyncio.create_task(self.run_unsudo(interaction))
        await asyncio.sleep(0.05)
        self.assertFalse(unsudo_task.done())
        self.assertEqual(calls, ["add-start"])
        release_role_add.set()
        await asyncio.gather(sudo_task, unsudo_task)

        self.assertEqual(calls, ["add-start", "add-end", "remove"])
        self.assertIsNone(self.db.get_sudo_grant(USER_ID))
