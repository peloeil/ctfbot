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


def _format_command_help(command: app_commands.Command | app_commands.Group) -> str:
    lines = [f"**/{command.qualified_name}**", command.description]
    if details := command.extras.get("help"):
        lines.extend(["", details])
    if isinstance(command, app_commands.Group):
        lines.extend(["", "サブコマンド:"])
        lines.extend(
            sorted(
                f"/{child.qualified_name} — {child.description}"
                for child in command.commands
            )
        )
        lines.append("詳細は `/help command:コマンド名` で確認できます。")
    else:
        parameters = command.parameters
        usage = " ".join(
            [f"/{command.qualified_name}"]
            + [
                f"<{param.display_name}>"
                if param.required
                else f"[{param.display_name}]"
                for param in parameters
            ]
        )
        lines.extend(
            ["", f"使い方: `{usage}`", "引数:" if parameters else "引数: なし"]
        )
        for param in parameters:
            requirement = "必須" if param.required else "任意"
            if not param.required and param.default is not None:
                default = next(
                    (
                        choice.name
                        for choice in param.choices
                        if choice.value == param.default
                    ),
                    param.default,
                )
                requirement += f"、既定値: {default}"
            lines.append(
                f"- `{param.display_name}` ({requirement}): {param.description}"
            )
            if param.choices:
                lines.append(
                    "  選択肢: " + "、".join(choice.name for choice in param.choices)
                )
    return "\n".join(lines)


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

    @app_commands.command(
        name="roll",
        description="NdM形式でダイスを振ります。",
        extras={
            "help": "N 個の M 面ダイスを振り、各出目と合計をチャンネルに公開します。\n"
            "個数・面数はいずれも 1〜100 です。例: `/roll notation:3d6`"
        },
    )
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
        name="help",
        description="利用可能なコマンドの一覧・詳細を表示します。",
        extras={
            "help": "引数なしで一覧、コマンド名を指定すると使い方と引数を表示します。\n"
            "例: `/help command:roll`、`/help command:ctfteam open`\n"
            "先頭の / は省略できます。ヘルプは実行者だけに表示します。"
        },
    )
    @app_commands.describe(command="詳細を表示するコマンド名 (例: roll、ctfteam open)")
    async def help_command(
        self, interaction: discord.Interaction, command: str | None = None
    ) -> None:
        if interaction.guild is None:
            await send_interaction(interaction, "サーバー内で実行してください。")
            return
        # Commands are copied to the guild at startup; use that registered set.
        registered = self.bot.tree.get_commands(guild=interaction.guild)
        if command is not None:
            parts = command.strip().removeprefix("/").split()
            target = next(
                (item for item in registered if parts and item.name == parts[0]), None
            )
            for name in parts[1:]:
                target = (
                    target.get_command(name)
                    if isinstance(target, app_commands.Group)
                    else None
                )
            if not isinstance(target, app_commands.Command | app_commands.Group):
                await send_interaction(
                    interaction,
                    "コマンドが見つかりません。/help で一覧を確認してください。",
                )
                return
            await send_interaction(interaction, _format_command_help(target))
            return

        lines: list[str] = []
        for item in registered:
            if isinstance(item, app_commands.Group):
                for child in item.commands:
                    lines.append(f"/{child.qualified_name} — {child.description}")
            elif isinstance(item, app_commands.Command):
                lines.append(f"/{item.name} — {item.description}")
        await send_interaction(interaction, "\n".join(sorted(lines)))

    @app_commands.command(
        name="perms",
        description="botまたはロールのサーバー/チャンネル権限を表示します。",
        extras={
            "help": "サーバー全体の実効権限と、チャンネルでの権限の増減を表示します。\n"
            "省略時は bot 自身と実行チャンネルが対象です。"
            "ロールを指定すると @everyone の権限も合成して確認します。\n"
            "結果は実行者だけに表示します。"
        },
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
