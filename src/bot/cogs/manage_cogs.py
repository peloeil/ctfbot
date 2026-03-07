from typing import ClassVar

import discord
from discord import app_commands
from discord.ext import commands

from ..utils.helpers import logger, send_interaction_message


class ManageCogs(
    commands.GroupCog,
    group_name="cog",
    group_description="Cogの読み込み関連コマンドです。",
):
    """Slash commands for loading/unloading/reloading cogs."""

    CORE_COGS: ClassVar[set[str]] = {
        "manage_cogs",
        "help_command",
        "message_tools",
        "perms_debug",
        "times_channels",
    }
    FEATURE_COGS: ClassVar[set[str]] = {"alpacahack", "ctf_roles", "ctftime"}
    LEGACY_CORE_ALIASES: ClassVar[dict[str, str]] = {"slash_commands": "message_tools"}

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _defer_ephemeral(self, interaction: discord.Interaction) -> None:
        if interaction.response.is_done():
            return
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.InteractionResponded:
            return
        except (discord.NotFound, discord.HTTPException):
            logger.warning(
                "Failed to defer interaction in manage_cogs: id=%s",
                interaction.id,
            )

    def _normalize_extension(self, name: str) -> str:
        normalized = name.strip().removesuffix(".py")
        normalized = self.LEGACY_CORE_ALIASES.get(normalized, normalized)
        if normalized in self.CORE_COGS:
            return f"bot.cogs.{normalized}"
        if normalized in self.FEATURE_COGS:
            return f"bot.features.{normalized}.cog"

        if normalized.startswith("bot."):
            return normalized
        if normalized.startswith("cogs."):
            return f"bot.{normalized}"
        if normalized.startswith("features."):
            return f"bot.{normalized}"
        return f"bot.features.{normalized}.cog"

    @app_commands.command(name="sync")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def sync(self, interaction: discord.Interaction) -> None:
        await self._defer_ephemeral(interaction)
        if interaction.guild is None:
            await send_interaction_message(
                interaction,
                "このコマンドはサーバー内でのみ使用できます。",
                ephemeral=True,
            )
            return

        try:
            guild_synced = await self.bot.tree.sync(guild=interaction.guild)
            await send_interaction_message(
                interaction,
                f"Guild sync: {len(guild_synced)} command(s)",
                ephemeral=True,
            )
        except Exception as error:
            logger.exception("Failed to sync commands")
            await send_interaction_message(
                interaction,
                f"Failed to sync commands: {error}",
                ephemeral=True,
            )

    @app_commands.command(name="load")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def load(self, interaction: discord.Interaction, name: str) -> None:
        await self._defer_ephemeral(interaction)
        extension = self._normalize_extension(name)
        try:
            await self.bot.load_extension(extension)
            await send_interaction_message(interaction, f"Loaded {extension}")
        except Exception as error:
            logger.exception("Failed to load extension %s", extension)
            await send_interaction_message(
                interaction,
                f"Failed to load {extension}: {error}",
            )

    @app_commands.command(name="unload")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def unload(self, interaction: discord.Interaction, name: str) -> None:
        await self._defer_ephemeral(interaction)
        extension = self._normalize_extension(name)
        if extension == "bot.cogs.manage_cogs":
            await send_interaction_message(
                interaction,
                "この cog は unload できません。",
            )
            return

        try:
            await self.bot.unload_extension(extension)
            await send_interaction_message(interaction, f"Unloaded {extension}")
        except Exception as error:
            logger.exception("Failed to unload extension %s", extension)
            await send_interaction_message(
                interaction,
                f"Failed to unload {extension}: {error}",
            )

    @app_commands.command(name="reload")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reload(self, interaction: discord.Interaction, name: str) -> None:
        await self._defer_ephemeral(interaction)
        extension = self._normalize_extension(name)
        try:
            await self.bot.reload_extension(extension)
            await send_interaction_message(interaction, f"Reloaded {extension}")
        except Exception as error:
            logger.exception("Failed to reload extension %s", extension)
            await send_interaction_message(
                interaction,
                f"Failed to reload {extension}: {error}",
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(ManageCogs(bot))
