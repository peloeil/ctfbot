import random
import re

import discord
from discord import app_commands
from discord.ext import commands

from ctfbot.helpers import MAX_MESSAGE_CONTENT_LENGTH, send_interaction

_PERMISSION_NAMES = {
    "read_messages": "view_channel",
    "external_emojis": "use_external_emojis",
    "external_stickers": "use_external_stickers",
}


def _format_permissions(scope: str, permissions: discord.Permissions) -> list[str]:
    enabled: list[str] = []
    disabled: list[str] = []
    for name, value in permissions:
        (enabled if value else disabled).append(_PERMISSION_NAMES.get(name, name))
    return [
        f"{scope} ✅ {'、'.join(enabled) or 'なし'}",
        f"{scope} ❌ {'、'.join(disabled) or 'なし'}",
    ]


def _format_permission_diff(
    guild_permissions: discord.Permissions,
    channel_permissions: discord.Permissions,
) -> list[str]:
    added: list[str] = []
    removed: list[str] = []
    for name, guild_value in guild_permissions:
        channel_value = getattr(channel_permissions, name)
        if guild_value != channel_value:
            target = added if channel_value else removed
            target.append(_PERMISSION_NAMES.get(name, name))
    if not added and not removed:
        return ["Channel 差分なし"]
    return [
        f"Channel 追加 ✅ {'、'.join(added) or 'なし'}",
        f"Channel 削除 ❌ {'、'.join(removed) or 'なし'}",
    ]


def _guild_permissions_for(
    guild: discord.Guild, subject: discord.Member | discord.Role
) -> discord.Permissions:
    if isinstance(subject, discord.Member):
        return subject.guild_permissions
    permissions = guild.default_role.permissions | subject.permissions
    return discord.Permissions.all() if permissions.administrator else permissions


def _permission_pages(
    header: list[str],
    guild_permissions: discord.Permissions,
    channel_permissions: discord.Permissions,
) -> list[str]:
    guild_lines = _format_permissions("Guild", guild_permissions)
    channel_lines = _format_permission_diff(guild_permissions, channel_permissions)
    content = "\n".join([*header, *guild_lines, *channel_lines])
    if len(content) <= MAX_MESSAGE_CONTENT_LENGTH:
        return [content]
    return ["\n".join([*header, *guild_lines]), "\n".join(channel_lines)]


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
        name="perms",
        description="botまたはロールのサーバー/チャンネル権限を表示します。",
    )
    @app_commands.describe(
        channel="確認対象チャンネル (省略時は実行チャンネル)",
        role="確認対象ロール (省略時はbot)",
    )
    async def perms_check(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        role: discord.Role | None = None,
    ) -> None:
        guild = interaction.guild
        if guild is None or guild.me is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.abc.GuildChannel):
            await send_interaction(interaction, "チャンネル権限を確認できません。")
            return

        subject = role or guild.me
        header = [
            f"対象: {subject.mention} (ID: {subject.id})",
            f"チャンネル: {target.mention} (ID: {target.id})",
        ]
        if role is not None:
            header.append(f"ロール順位: {role.position}")
        pages = _permission_pages(
            header,
            _guild_permissions_for(guild, subject),
            target.permissions_for(subject),
        )
        for page in pages:
            await send_interaction(interaction, page)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCommands(bot))
