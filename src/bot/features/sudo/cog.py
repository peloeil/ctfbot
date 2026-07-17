import asyncio
import time
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.errors import RepositoryError, ServiceError
from bot.features.sudo.models import SudoGrant
from bot.helpers import (
    log_audit,
    require_guild,
    resolve_messageable,
    send_interaction,
    send_safely,
)
from bot.log import logger
from bot.runtime import get_runtime

ROLE_ADD_ERROR = (
    "ロールを付与できません。bot のロール権限と順位を確認してください(/perms)。"
)
ROLE_REMOVE_ERROR = (
    "ロールを解除できません。bot のロール権限と順位を確認してください(/perms)。"
)


class Sudo(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        runtime = get_runtime(bot)
        self.bot = bot
        self.settings = runtime.settings
        self.db = runtime.db
        self._grant_locks: defaultdict[tuple[int, int], asyncio.Lock] = defaultdict(
            asyncio.Lock
        )
        self.revoke_expired_grants.start()

    async def cog_unload(self) -> None:
        self.revoke_expired_grants.cancel()

    @app_commands.command(name="sudo", description="管理者ロールを一時的に取得します。")
    async def sudo(self, interaction: discord.Interaction) -> None:
        try:
            guild = require_guild(interaction)
            admin_role_id, sudoer_role_id = self._require_configuration()
            member = self._require_sudoer(interaction, sudoer_role_id)

            lock = self._grant_locks[guild.id, member.id]
            async with lock:
                grant = await asyncio.to_thread(
                    self.db.get_sudo_grant, guild.id, member.id
                )
                role, grant = await self._resolve_sudo_role(
                    guild, member, admin_role_id, grant
                )
                is_renewal = grant is not None
                now_unix = int(time.time())
                expires_at_unix = now_unix + self.settings.sudo_duration_minutes * 60
                await asyncio.to_thread(
                    self.db.upsert_sudo_grant,
                    guild.id,
                    member.id,
                    role.id,
                    now_unix,
                    expires_at_unix,
                )
                if not self._has_role(member, role.id):
                    try:
                        await member.add_roles(role)
                    except discord.Forbidden, discord.HTTPException:
                        await self._restore_grant_after_role_add_failure(
                            guild.id, member.id, grant
                        )
                        raise ServiceError(ROLE_ADD_ERROR) from None

            if is_renewal:
                message = f"⏫ 有効期限を <t:{expires_at_unix}:R> に延長しました。"
            else:
                message = (
                    "⏫ 管理者ロールを付与しました。"
                    f"<t:{expires_at_unix}:R> に自動解除されます。"
                )
        except ServiceError as exc:
            await send_interaction(interaction, str(exc))
            return

        await send_interaction(interaction, message)
        await log_audit(
            self.bot,
            interaction,
            command_name="sudo",
            details=[f"管理者ロール期限: <t:{expires_at_unix}:f>"],
        )

    @app_commands.command(name="unsudo", description="管理者ロールを解除します。")
    async def unsudo(self, interaction: discord.Interaction) -> None:
        try:
            guild = require_guild(interaction)
            member = self._require_member(interaction)
            lock = self._grant_locks[guild.id, member.id]
            async with lock:
                grant = await asyncio.to_thread(
                    self.db.get_sudo_grant, guild.id, member.id
                )
                if grant is None:
                    raise ServiceError("昇格中ではありません。")

                role = guild.get_role(grant.role_id)
                if role is not None:
                    try:
                        await member.remove_roles(role)
                    except discord.NotFound:
                        pass
                    except discord.Forbidden, discord.HTTPException:
                        raise ServiceError(ROLE_REMOVE_ERROR) from None

                await asyncio.to_thread(self.db.delete_sudo_grant, guild.id, member.id)
        except ServiceError as exc:
            await send_interaction(interaction, str(exc))
            return

        await send_interaction(interaction, "⏬ 管理者ロールを解除しました。")
        await log_audit(
            self.bot,
            interaction,
            command_name="unsudo",
            details=[f"管理者ロールID: {grant.role_id}"],
        )

    def _require_configuration(self) -> tuple[int, int]:
        admin_role_id = self.settings.admin_role_id
        sudoer_role_id = self.settings.sudoer_role_id
        if admin_role_id is None or sudoer_role_id is None:
            raise ServiceError("sudo 機能が設定されていません。")
        return admin_role_id, sudoer_role_id

    @staticmethod
    def _require_member(interaction: discord.Interaction) -> discord.Member:
        member = interaction.user
        if not isinstance(member, discord.Member):
            raise ServiceError("昇格中ではありません。")
        return member

    @classmethod
    def _require_sudoer(
        cls, interaction: discord.Interaction, sudoer_role_id: int
    ) -> discord.Member:
        member = interaction.user
        if not isinstance(member, discord.Member) or not cls._has_role(
            member, sudoer_role_id
        ):
            raise ServiceError("このコマンドを実行するには sudoer ロールが必要です。")
        return member

    @staticmethod
    def _has_role(member: discord.Member, role_id: int) -> bool:
        return any(role.id == role_id for role in member.roles)

    async def _resolve_sudo_role(
        self,
        guild: discord.Guild,
        member: discord.Member,
        admin_role_id: int,
        grant: SudoGrant | None,
    ) -> tuple[discord.Role, SudoGrant | None]:
        if grant is not None:
            granted_role = guild.get_role(grant.role_id)
            if granted_role is not None:
                return granted_role, grant
            await asyncio.to_thread(
                self.db.delete_sudo_grant, grant.guild_id, grant.user_id
            )
            grant = None

        configured_role = guild.get_role(admin_role_id)
        if configured_role is None:
            raise ServiceError("付与対象のロールが見つかりません。")
        if self._has_role(member, configured_role.id):
            raise ServiceError("既に管理者ロールを保持しています。")
        return configured_role, None

    async def _restore_grant_after_role_add_failure(
        self,
        guild_id: int,
        user_id: int,
        previous_grant: SudoGrant | None,
    ) -> None:
        try:
            if previous_grant is None:
                await asyncio.to_thread(self.db.delete_sudo_grant, guild_id, user_id)
                return
            await asyncio.to_thread(
                self.db.upsert_sudo_grant,
                previous_grant.guild_id,
                previous_grant.user_id,
                previous_grant.role_id,
                previous_grant.granted_at_unix,
                previous_grant.expires_at_unix,
            )
        except RepositoryError:
            logger.exception(
                "Failed to restore sudo grant after role assignment failure"
            )

    @tasks.loop(minutes=1)
    async def revoke_expired_grants(self) -> None:
        try:
            now_unix = int(time.time())
            grants = await asyncio.to_thread(self.db.list_expired_sudo_grants, now_unix)
            for grant in grants:
                try:
                    await self._revoke_expired_grant(grant, now_unix)
                except Exception:
                    logger.exception(
                        "Failed to process expired sudo grant for member %s "
                        "in guild %s",
                        grant.user_id,
                        grant.guild_id,
                    )
        except Exception:
            logger.exception("Error in revoke_expired_grants")

    @revoke_expired_grants.before_loop
    async def before_revoke_expired_grants(self) -> None:
        await self.bot.wait_until_ready()

    async def _revoke_expired_grant(
        self, candidate: SudoGrant, now_unix: int | None = None
    ) -> None:
        lock = self._grant_locks[candidate.guild_id, candidate.user_id]
        async with lock:
            grant = await asyncio.to_thread(
                self.db.get_sudo_grant, candidate.guild_id, candidate.user_id
            )
            if grant is None:
                return
            cutoff = int(time.time()) if now_unix is None else now_unix
            if grant.expires_at_unix > cutoff:
                return

            guild = self.bot.get_guild(grant.guild_id)
            if guild is None:
                return

            member, confirmed_absent = await self._resolve_member(guild, grant.user_id)
            if member is None:
                if confirmed_absent:
                    await asyncio.to_thread(
                        self.db.delete_sudo_grant, grant.guild_id, grant.user_id
                    )
                return

            role = guild.get_role(grant.role_id)
            if role is not None:
                try:
                    await member.remove_roles(role)
                except discord.NotFound:
                    pass
                except discord.Forbidden, discord.HTTPException:
                    logger.warning(
                        "Failed to revoke sudo role from member %s in guild %s",
                        grant.user_id,
                        grant.guild_id,
                    )
                    return

            await asyncio.to_thread(
                self.db.delete_sudo_grant, grant.guild_id, grant.user_id
            )

        channel = await resolve_messageable(self.bot, self.settings.bot_channel_id)
        if channel is not None:
            await send_safely(
                channel,
                f"⏬ {member.display_name} (id={member.id}) "
                "の管理者ロールを自動解除しました。",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @staticmethod
    async def _resolve_member(
        guild: discord.Guild, user_id: int
    ) -> tuple[discord.Member | None, bool]:
        member = guild.get_member(user_id)
        if member is not None:
            return member, False
        try:
            return await guild.fetch_member(user_id), False
        except discord.NotFound:
            return None, True
        except discord.Forbidden, discord.HTTPException:
            return None, False


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Sudo(bot))
