import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


async def _respond_ephemeral(interaction: discord.Interaction, content: str) -> None:
    # bot 内部依存を持たない cog のため helpers.send_interaction を使わず、
    # 同じ応答契約 (docs/core.md) をここで満たす
    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                content,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await interaction.response.send_message(
                content,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
    except (
        discord.InteractionResponded,
        discord.NotFound,
        discord.HTTPException,
    ):
        logger.exception("Failed to send interaction response")


class UtilityCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="help", description="利用可能なコマンド一覧を表示します。"
    )
    async def help_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await _respond_ephemeral(interaction, "サーバー内で実行してください。")
            return
        lines: list[str] = []
        for command in self.bot.tree.get_commands():
            if isinstance(command, app_commands.Group):
                for child in command.commands:
                    lines.append(f"/{command.name} {child.name} — {child.description}")
            elif isinstance(command, app_commands.Command):
                lines.append(f"/{command.name} — {command.description}")
        await _respond_ephemeral(interaction, "\n".join(sorted(lines)))

    @app_commands.command(
        name="perms", description="このサーバー/チャンネルでのbot権限を表示します。"
    )
    @app_commands.describe(channel="確認対象チャンネル (省略時は実行チャンネル)")
    async def perms_check(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None or guild.me is None:
            await _respond_ephemeral(interaction, "サーバー内で実行してください。")
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.abc.GuildChannel):
            await _respond_ephemeral(interaction, "チャンネル権限を確認できません。")
            return

        guild_permissions = guild.me.guild_permissions
        channel_permissions = target.permissions_for(guild.me)
        checks = [
            ("Guild view_audit_log", guild_permissions.view_audit_log),
            ("Guild manage_roles", guild_permissions.manage_roles),
            ("Channel view_channel", channel_permissions.view_channel),
            ("Channel send_messages", channel_permissions.send_messages),
            (
                "Channel send_messages_in_threads",
                channel_permissions.send_messages_in_threads,
            ),
            ("Channel read_message_history", channel_permissions.read_message_history),
            ("Channel add_reactions", channel_permissions.add_reactions),
            ("Channel manage_channels", channel_permissions.manage_channels),
            ("Channel embed_links", channel_permissions.embed_links),
        ]
        content = "\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks)
        await _respond_ephemeral(interaction, content)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCommands(bot))
