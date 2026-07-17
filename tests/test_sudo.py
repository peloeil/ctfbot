import asyncio
import unittest
from collections import defaultdict
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

import discord
from discord.ext import commands

from bot.features.sudo.cog import ROLE_ADD_ERROR, ROLE_REMOVE_ERROR, Sudo
from bot.features.sudo.models import SudoGrant


class SudoTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot = mock.Mock(spec=commands.Bot)
        self.db = mock.Mock()
        self.cog = object.__new__(Sudo)
        self.cog.bot = self.bot
        self.cog.db = self.db
        self.cog._grant_locks = defaultdict(asyncio.Lock)
        self.cog.settings = SimpleNamespace(
            admin_role_id=10,
            sudoer_role_id=20,
            sudo_duration_minutes=30,
            bot_channel_id=30,
        )

    @staticmethod
    def make_interaction(
        *,
        member_roles: list[mock.Mock] | None = None,
        admin_role: mock.Mock | None = None,
    ) -> tuple[discord.Interaction, mock.Mock, mock.Mock, mock.Mock]:
        sudoer_role = mock.Mock(spec=discord.Role, id=20)
        role = admin_role or mock.Mock(spec=discord.Role, id=10)
        member = mock.Mock(spec=discord.Member, id=2, display_name="alice")
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

    async def test_sudo_rejects_member_without_sudoer_role(self) -> None:
        interaction, _, _, _ = self.make_interaction(member_roles=[])
        with mock.patch(
            "bot.features.sudo.cog.send_interaction", new_callable=mock.AsyncMock
        ) as send_interaction:
            callback = cast(Any, self.cog.sudo.callback)
            await callback(self.cog, interaction)

        send_interaction.assert_awaited_once_with(
            interaction, "このコマンドを実行するには sudoer ロールが必要です。"
        )
        self.db.get_sudo_grant.assert_not_called()

    async def test_sudo_does_not_convert_permanent_role_to_grant(self) -> None:
        admin_role = mock.Mock(spec=discord.Role, id=10)
        sudoer_role = mock.Mock(spec=discord.Role, id=20)
        interaction, _, _, _ = self.make_interaction(
            member_roles=[sudoer_role, admin_role], admin_role=admin_role
        )
        self.db.get_sudo_grant.return_value = None
        with mock.patch(
            "bot.features.sudo.cog.send_interaction", new_callable=mock.AsyncMock
        ) as send_interaction:
            callback = cast(Any, self.cog.sudo.callback)
            await callback(self.cog, interaction)

        send_interaction.assert_awaited_once_with(
            interaction, "既に管理者ロールを保持しています。"
        )
        self.db.upsert_sudo_grant.assert_not_called()

    async def test_sudo_records_grant_before_adding_role(self) -> None:
        interaction, _, member, role = self.make_interaction()
        self.db.get_sudo_grant.return_value = None
        calls: list[str] = []
        self.db.upsert_sudo_grant.side_effect = lambda *args: calls.append("db")
        member.add_roles.side_effect = lambda *args: calls.append("discord")

        async def run_in_thread(function, *args):
            return function(*args)

        with (
            mock.patch("bot.features.sudo.cog.time.time", return_value=100),
            mock.patch(
                "bot.features.sudo.cog.asyncio.to_thread", side_effect=run_in_thread
            ),
            mock.patch(
                "bot.features.sudo.cog.send_interaction", new_callable=mock.AsyncMock
            ) as send_interaction,
            mock.patch(
                "bot.features.sudo.cog.log_audit", new_callable=mock.AsyncMock
            ) as log_audit,
        ):
            callback = cast(Any, self.cog.sudo.callback)
            await callback(self.cog, interaction)

        self.assertEqual(calls, ["db", "discord"])
        self.db.upsert_sudo_grant.assert_called_once_with(1, 2, 10, 100, 1900)
        member.add_roles.assert_awaited_once_with(role)
        send_interaction.assert_awaited_once_with(
            interaction,
            "⏫ 管理者ロールを付与しました。<t:1900:R> に自動解除されます。",
        )
        log_audit.assert_awaited_once()

    async def test_sudo_deletes_grant_when_role_assignment_fails(self) -> None:
        interaction, _, member, _ = self.make_interaction()
        self.db.get_sudo_grant.return_value = None
        response = mock.Mock(status=403, reason="Forbidden")
        member.add_roles.side_effect = discord.Forbidden(response, "denied")

        with mock.patch(
            "bot.features.sudo.cog.send_interaction", new_callable=mock.AsyncMock
        ) as send_interaction:
            callback = cast(Any, self.cog.sudo.callback)
            await callback(self.cog, interaction)

        self.db.delete_sudo_grant.assert_called_once_with(1, 2)
        send_interaction.assert_awaited_once_with(interaction, ROLE_ADD_ERROR)

    async def test_sudo_renewal_uses_original_role_after_config_change(self) -> None:
        configured_role = mock.Mock(spec=discord.Role, id=10)
        granted_role = mock.Mock(spec=discord.Role, id=9)
        sudoer_role = mock.Mock(spec=discord.Role, id=20)
        interaction, guild, member, _ = self.make_interaction(
            member_roles=[sudoer_role, granted_role],
            admin_role=configured_role,
        )
        guild.get_role.side_effect = {
            configured_role.id: configured_role,
            granted_role.id: granted_role,
        }.get
        self.db.get_sudo_grant.return_value = SudoGrant(1, 2, 9, 50, 200)

        with (
            mock.patch("bot.features.sudo.cog.time.time", return_value=100),
            mock.patch(
                "bot.features.sudo.cog.send_interaction", new_callable=mock.AsyncMock
            ) as send_interaction,
            mock.patch("bot.features.sudo.cog.log_audit", new_callable=mock.AsyncMock),
        ):
            callback = cast(Any, self.cog.sudo.callback)
            await callback(self.cog, interaction)

        self.db.upsert_sudo_grant.assert_called_once_with(1, 2, 9, 100, 1900)
        member.add_roles.assert_not_awaited()
        send_interaction.assert_awaited_once_with(
            interaction, "⏫ 有効期限を <t:1900:R> に延長しました。"
        )

    async def test_sudo_renewal_uses_saved_role_when_configured_role_is_missing(
        self,
    ) -> None:
        granted_role = mock.Mock(spec=discord.Role, id=9)
        sudoer_role = mock.Mock(spec=discord.Role, id=20)
        interaction, guild, member, _ = self.make_interaction(
            member_roles=[sudoer_role, granted_role]
        )
        guild.get_role.side_effect = {9: granted_role, 10: None}.get
        self.db.get_sudo_grant.return_value = SudoGrant(1, 2, 9, 50, 200)

        with (
            mock.patch("bot.features.sudo.cog.time.time", return_value=100),
            mock.patch(
                "bot.features.sudo.cog.send_interaction", new_callable=mock.AsyncMock
            ) as send_interaction,
            mock.patch("bot.features.sudo.cog.log_audit", new_callable=mock.AsyncMock),
        ):
            callback = cast(Any, self.cog.sudo.callback)
            await callback(self.cog, interaction)

        self.db.upsert_sudo_grant.assert_called_once_with(1, 2, 9, 100, 1900)
        member.add_roles.assert_not_awaited()
        self.assertEqual(guild.get_role.call_args_list, [mock.call(9)])
        send_interaction.assert_awaited_once_with(
            interaction, "⏫ 有効期限を <t:1900:R> に延長しました。"
        )

    async def test_sudo_without_grant_rejects_missing_configured_role(self) -> None:
        interaction, guild, _, _ = self.make_interaction()
        guild.get_role.return_value = None
        self.db.get_sudo_grant.return_value = None

        with mock.patch(
            "bot.features.sudo.cog.send_interaction", new_callable=mock.AsyncMock
        ) as send_interaction:
            callback = cast(Any, self.cog.sudo.callback)
            await callback(self.cog, interaction)

        send_interaction.assert_awaited_once_with(
            interaction, "付与対象のロールが見つかりません。"
        )
        self.db.upsert_sudo_grant.assert_not_called()

    async def test_sudo_failed_renewal_restores_previous_grant(self) -> None:
        interaction, _, member, _ = self.make_interaction()
        previous = SudoGrant(1, 2, 10, 50, 200)
        self.db.get_sudo_grant.return_value = previous
        response = mock.Mock(status=403, reason="Forbidden")
        member.add_roles.side_effect = discord.Forbidden(response, "denied")

        async def run_in_thread(function, *args):
            return function(*args)

        with (
            mock.patch("bot.features.sudo.cog.time.time", return_value=100),
            mock.patch(
                "bot.features.sudo.cog.asyncio.to_thread", side_effect=run_in_thread
            ),
            mock.patch(
                "bot.features.sudo.cog.send_interaction", new_callable=mock.AsyncMock
            ) as send_interaction,
        ):
            callback = cast(Any, self.cog.sudo.callback)
            await callback(self.cog, interaction)

        self.assertEqual(
            self.db.upsert_sudo_grant.call_args_list,
            [
                mock.call(1, 2, 10, 100, 1900),
                mock.call(1, 2, 10, 50, 200),
            ],
        )
        self.db.delete_sudo_grant.assert_not_called()
        send_interaction.assert_awaited_once_with(interaction, ROLE_ADD_ERROR)

    async def test_unsudo_keeps_grant_when_role_removal_fails(self) -> None:
        interaction, _, member, _ = self.make_interaction()
        self.db.get_sudo_grant.return_value = SudoGrant(1, 2, 10, 100, 200)
        response = mock.Mock(status=403, reason="Forbidden")
        member.remove_roles.side_effect = discord.Forbidden(response, "denied")

        with mock.patch(
            "bot.features.sudo.cog.send_interaction", new_callable=mock.AsyncMock
        ) as send_interaction:
            callback = cast(Any, self.cog.unsudo.callback)
            await callback(self.cog, interaction)

        self.db.delete_sudo_grant.assert_not_called()
        send_interaction.assert_awaited_once_with(interaction, ROLE_REMOVE_ERROR)

    async def test_expired_grant_removes_role_then_record_and_notifies(self) -> None:
        grant = SudoGrant(1, 2, 10, 100, 200)
        _, guild, member, role = self.make_interaction()
        self.db.get_sudo_grant.return_value = grant
        guild.get_member.return_value = member
        self.bot.get_guild.return_value = guild
        channel = mock.Mock()
        calls: list[str] = []
        member.remove_roles.side_effect = lambda *args: calls.append("discord")
        self.db.delete_sudo_grant.side_effect = lambda *args: calls.append("db")

        async def run_in_thread(function, *args):
            return function(*args)

        with (
            mock.patch(
                "bot.features.sudo.cog.asyncio.to_thread", side_effect=run_in_thread
            ),
            mock.patch(
                "bot.features.sudo.cog.resolve_messageable",
                new_callable=mock.AsyncMock,
                return_value=channel,
            ),
            mock.patch(
                "bot.features.sudo.cog.send_safely", new_callable=mock.AsyncMock
            ) as send_safely,
        ):
            await self.cog._revoke_expired_grant(grant)

        self.assertEqual(calls, ["discord", "db"])
        member.remove_roles.assert_awaited_once_with(role)
        self.db.delete_sudo_grant.assert_called_once_with(1, 2)
        send_safely.assert_awaited_once()

    async def test_expired_grant_for_departed_member_deletes_only_record(self) -> None:
        grant = SudoGrant(1, 2, 10, 100, 200)
        _, guild, _, _ = self.make_interaction()
        self.db.get_sudo_grant.return_value = grant
        guild.get_member.return_value = None
        response = mock.Mock(status=404, reason="Not Found")
        guild.fetch_member = mock.AsyncMock(
            side_effect=discord.NotFound(response, "missing")
        )
        self.bot.get_guild.return_value = guild

        await self.cog._revoke_expired_grant(grant)

        self.db.delete_sudo_grant.assert_called_once_with(1, 2)
        guild.get_role.assert_not_called()

    async def test_expired_grant_keeps_record_when_member_lookup_fails(self) -> None:
        grant = SudoGrant(1, 2, 10, 100, 200)
        _, guild, _, _ = self.make_interaction()
        self.db.get_sudo_grant.return_value = grant
        guild.get_member.return_value = None
        response = mock.Mock(status=403, reason="Forbidden")
        guild.fetch_member = mock.AsyncMock(
            side_effect=discord.Forbidden(response, "denied")
        )
        self.bot.get_guild.return_value = guild

        await self.cog._revoke_expired_grant(grant)

        self.db.delete_sudo_grant.assert_not_called()
        guild.get_role.assert_not_called()

    async def test_expired_snapshot_does_not_revoke_renewed_grant(self) -> None:
        candidate = SudoGrant(1, 2, 10, 100, 200)
        renewed = SudoGrant(1, 2, 10, 100, 1900)
        self.db.get_sudo_grant.return_value = renewed

        await self.cog._revoke_expired_grant(candidate, now_unix=300)

        self.db.delete_sudo_grant.assert_not_called()
        self.bot.get_guild.assert_not_called()

    async def test_unsudo_waits_for_in_flight_sudo_transition(self) -> None:
        interaction, _, member, _ = self.make_interaction()
        grant = SudoGrant(1, 2, 10, 100, 1900)
        self.db.get_sudo_grant.side_effect = [None, grant]
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

        async def run_in_thread(function, *args):
            return function(*args)

        member.add_roles.side_effect = add_role
        member.remove_roles.side_effect = remove_role

        with (
            mock.patch("bot.features.sudo.cog.time.time", return_value=100),
            mock.patch(
                "bot.features.sudo.cog.asyncio.to_thread", side_effect=run_in_thread
            ),
            mock.patch(
                "bot.features.sudo.cog.send_interaction", new_callable=mock.AsyncMock
            ),
            mock.patch("bot.features.sudo.cog.log_audit", new_callable=mock.AsyncMock),
        ):
            sudo_callback = cast(Any, self.cog.sudo.callback)
            unsudo_callback = cast(Any, self.cog.unsudo.callback)
            sudo_task = asyncio.create_task(sudo_callback(self.cog, interaction))
            await role_add_started.wait()
            unsudo_task = asyncio.create_task(unsudo_callback(self.cog, interaction))
            await asyncio.sleep(0)
            self.assertEqual(self.db.get_sudo_grant.call_count, 1)
            release_role_add.set()
            await asyncio.gather(sudo_task, unsudo_task)

        self.assertEqual(calls, ["add-start", "add-end", "remove"])
        self.db.delete_sudo_grant.assert_called_once_with(1, 2)


if __name__ == "__main__":
    unittest.main()
