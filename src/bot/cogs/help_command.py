from __future__ import annotations

from collections.abc import Sequence

import discord
from discord import app_commands
from discord.ext import commands

from ..utils.helpers import send_interaction_message


class HelpCommand(commands.Cog):
    """Slash command for displaying available command list."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @classmethod
    def _flatten_slash_commands(
        cls,
        command_items: Sequence[app_commands.Command | app_commands.Group],
        *,
        prefix: str = "",
    ) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for command in sorted(command_items, key=lambda item: item.name):
            qualified = f"{prefix} {command.name}".strip()
            if isinstance(command, app_commands.Group):
                rows.extend(
                    cls._flatten_slash_commands(
                        list(command.commands),
                        prefix=qualified,
                    )
                )
                continue

            description = command.description.strip() or "説明なし"
            rows.append((qualified, description))
        return rows

    def _build_help_message(self, interaction: discord.Interaction) -> str:
        slash_commands = self.bot.tree.get_commands(
            type=discord.AppCommandType.chat_input,
        )

        if interaction.guild is not None:
            slash_commands.extend(
                self.bot.tree.get_commands(
                    guild=interaction.guild,
                    type=discord.AppCommandType.chat_input,
                )
            )

        flattened = self._flatten_slash_commands(slash_commands)
        deduped: dict[str, str] = {}
        for name, description in flattened:
            deduped.setdefault(name, description)

        if not deduped:
            return "利用可能なスラッシュコマンドはありません。"

        lines = ["**利用可能なスラッシュコマンド**"]
        lines.extend(
            f"- `/{name}`: {description}"
            for name, description in sorted(deduped.items(), key=lambda item: item[0])
        )
        lines.append("")
        lines.append("`/` 入力時の候補補完からも同じコマンドを確認できます。")

        content = "\n".join(lines)
        if len(content) > 1900:
            return f"{content[:1897]}..."
        return content

    @app_commands.command(
        name="help",
        description="利用可能なコマンド一覧を表示します。",
    )
    async def help(self, interaction: discord.Interaction) -> None:
        await send_interaction_message(
            interaction,
            self._build_help_message(interaction),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCommand(bot))
