import discord
from discord import app_commands
from discord.ext import commands

from ..utils.helpers import send_interaction_message


class PermissionsDebug(commands.Cog):
    """Slash command for bot permissions in guild/channel context."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _format_perm(value: bool) -> str:
        return "✅" if value else "❌"

    async def _fetch_member(
        self, guild: discord.Guild, user_id: int
    ) -> discord.Member | None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    @app_commands.command(
        name="perms",
        description="このサーバー/チャンネルでのbot権限を表示します。",
    )
    @app_commands.describe(channel="確認対象チャンネル(省略時は実行チャンネル)")
    async def perms(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        if interaction.guild is None:
            await send_interaction_message(
                interaction,
                "このコマンドはサーバー内でのみ使用できます。",
                ephemeral=True,
            )
            return

        target_channel = channel or interaction.channel
        if not isinstance(target_channel, discord.TextChannel):
            await send_interaction_message(
                interaction,
                "確認対象はテキストチャンネルを指定してください。",
                ephemeral=True,
            )
            return

        bot_user = self.bot.user
        if bot_user is None:
            await send_interaction_message(
                interaction,
                "botユーザー情報を取得できませんでした。",
                ephemeral=True,
            )
            return

        bot_member = await self._fetch_member(interaction.guild, bot_user.id)
        if bot_member is None:
            await send_interaction_message(
                interaction,
                "このサーバーでのbotメンバー情報を取得できませんでした。",
                ephemeral=True,
            )
            return

        guild_perms = bot_member.guild_permissions
        channel_perms = target_channel.permissions_for(bot_member)

        guild_checks = {
            "Manage Roles": guild_perms.manage_roles,
        }
        channel_checks = {
            "View Channel": channel_perms.view_channel,
            "Send Messages": channel_perms.send_messages,
            "Send Messages in Threads": channel_perms.send_messages_in_threads,
            "Read Message History": channel_perms.read_message_history,
            "Add Reactions": channel_perms.add_reactions,
            "Pin Messages": channel_perms.pin_messages,
            "Manage Channels": channel_perms.manage_channels,
        }

        guild_lines = [
            f"- {self._format_perm(ok)} {name}" for name, ok in guild_checks.items()
        ]
        channel_lines = [
            f"- {self._format_perm(ok)} {name}" for name, ok in channel_checks.items()
        ]

        content = "\n".join(
            [
                f"Bot: {bot_member.mention}",
                f"Top Role: `{bot_member.top_role.name}` "
                f"(position={bot_member.top_role.position})",
                "",
                "**Guild Permissions**",
                *guild_lines,
                "",
                f"**Channel Permissions ({target_channel.mention})**",
                *channel_lines,
            ]
        )
        if len(content) > 1900:
            content = f"{content[:1897]}..."

        await send_interaction_message(interaction, content, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PermissionsDebug(bot))
