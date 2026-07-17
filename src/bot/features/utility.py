import discord
from discord import app_commands
from discord.ext import commands


class UtilityCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="help", description="利用可能なコマンド一覧を表示します。"
    )
    async def help_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        lines: list[str] = []
        for command in self.bot.tree.get_commands():
            if isinstance(command, app_commands.Group):
                for child in command.commands:
                    lines.append(f"/{command.name} {child.name} — {child.description}")
            elif isinstance(command, app_commands.Command):
                lines.append(f"/{command.name} — {command.description}")
        await interaction.response.send_message(
            "\n".join(sorted(lines)), ephemeral=True
        )

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
            await interaction.response.send_message(
                "サーバー内で実行してください。", ephemeral=True
            )
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.abc.GuildChannel):
            await interaction.response.send_message(
                "チャンネル権限を確認できません。", ephemeral=True
            )
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
        ]
        content = "\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in checks)
        await interaction.response.send_message(content, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCommands(bot))
