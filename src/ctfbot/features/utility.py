import random
import re

import discord
from discord import app_commands
from discord.ext import commands

from ctfbot.helpers import send_interaction


class UtilityCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="roll", description="NdM形式でダイスを振ります。")
    @app_commands.describe(notation="ダイス表記 (例: 3d6)")
    async def roll(self, interaction: discord.Interaction, notation: str) -> None:
        match = re.fullmatch(r"([0-9]+)[dD]([0-9]+)", notation)
        if match is None:
            await send_interaction(
                interaction, "NdM 形式で指定してください (例: 3d6)。"
            )
            return
        count, sides = map(int, match.groups())
        if not 1 <= count <= 100 or not 1 <= sides <= 100:
            await send_interaction(
                interaction, "ダイスの個数と面数は 1〜100 で指定してください。"
            )
            return
        rolls = [random.randint(1, sides) for _ in range(count)]
        await send_interaction(
            interaction,
            f"🎲 {count}d{sides}: {', '.join(map(str, rolls))}\n合計: {sum(rolls)}",
            ephemeral=False,
        )

    @app_commands.command(
        name="help", description="利用可能なコマンド一覧を表示します。"
    )
    async def help_command(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        lines: list[str] = []
        # 起動時に copy_global_to で guild へコピーしたものが登録済みの一覧なので、
        # guild を指定して取得する
        for command in self.bot.tree.get_commands(guild=interaction.guild):
            if isinstance(command, app_commands.Group):
                for child in command.commands:
                    lines.append(f"/{command.name} {child.name} — {child.description}")
            elif isinstance(command, app_commands.Command):
                lines.append(f"/{command.name} — {command.description}")
        await send_interaction(interaction, "\n".join(sorted(lines)))

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
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.abc.GuildChannel):
            await send_interaction(interaction, "チャンネル権限を確認できません。")
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
        await send_interaction(interaction, content)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCommands(bot))
