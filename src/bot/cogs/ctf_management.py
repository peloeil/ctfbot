"""
CTF management cog for the CTF Discord bot.
Handles CTF event creation, role/channel management, and cleanup.
"""

from datetime import UTC, datetime
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from ..db.database import (
    create_ctf_events_table_if_not_exists,
    deactivate_ctf_event,
    get_ctf_event,
    get_ctf_events_to_end,
    insert_ctf_event,
    update_ctf_event,
)
from ..utils.helpers import handle_error, logger, send_message_safely


class CTFManagement(commands.Cog):
    """Cog for CTF event management including roles and channels."""

    def __init__(self, bot: commands.Bot):
        """
        Initialize the CTFManagement cog.

        Args:
            bot: The bot instance
        """
        self.bot = bot
        # Initialize database table
        create_ctf_events_table_if_not_exists()
        # Start the cleanup task
        self.cleanup_ended_ctfs.start()

    def cog_unload(self) -> None:
        """Clean up when the cog is unloaded."""
        self.cleanup_ended_ctfs.cancel()

    @app_commands.command(
        name="announce_ctf",
        description="CTFイベントを開始し、ロールとチャンネルを作成します。",
    )
    @app_commands.describe(name="CTF名（英数字とアンダースコアのみ）")
    async def announce_ctf(self, interaction: discord.Interaction, name: str) -> None:
        """
        Announce a new CTF event and create associated role and channels.

        Args:
            interaction: Command interaction
            name: CTF name (alphanumeric and underscores only)
        """
        if interaction.guild is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return

        # Validate CTF name
        if not name.replace("_", "").replace("-", "").isalnum():
            await interaction.response.send_message(
                "CTF名は英数字、アンダースコア、ハイフンのみ使用できます。",
                ephemeral=True,
            )
            return

        # Check if CTF already exists
        existing_ctf = get_ctf_event(name, interaction.guild.id)
        if existing_ctf:
            await interaction.response.send_message(
                f"CTF '{name}' は既に存在します。", ephemeral=True
            )
            return

        try:
            # Create role
            role = await interaction.guild.create_role(
                name=name,
                reason=f"CTF event: {name}",
                mentionable=True,
            )

            # Create text channel
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(
                    read_messages=False
                ),
                role: discord.PermissionOverwrite(read_messages=True),
            }
            text_channel = await interaction.guild.create_text_channel(
                name=name,
                overwrites=overwrites,
                reason=f"CTF event: {name}",
            )

            # Create voice channel
            voice_channel = await interaction.guild.create_voice_channel(
                name=name,
                overwrites=overwrites,
                reason=f"CTF event: {name}",
            )

            # Send announcement message
            embed = discord.Embed(
                title=f"🚩 CTF: {name}",
                description=f"CTF '{name}' が開始されました！\n\n"
                f"参加するには下の 🚩 リアクションをクリックしてください。\n"
                f"参加すると {role.mention} ロールが付与され、専用チャンネルにアクセスできます。",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="📝 テキストチャンネル",
                value=text_channel.mention,
                inline=True,
            )
            embed.add_field(
                name="🔊 ボイスチャンネル",
                value=voice_channel.mention,
                inline=True,
            )

            await interaction.response.send_message(embed=embed)
            message = await interaction.original_response()

            # Add reaction
            await message.add_reaction("🚩")

            # Save to database
            insert_ctf_event(
                name=name,
                guild_id=interaction.guild.id,
                role_id=role.id,
                text_channel_id=text_channel.id,
                voice_channel_id=voice_channel.id,
                announcement_message_id=message.id,
            )

            logger.info(f"Created CTF event '{name}' in guild {interaction.guild.id}")

        except discord.Forbidden:
            await interaction.response.send_message(
                "ロールやチャンネルを作成する権限がありません。", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                handle_error(e, "CTFイベントの作成に失敗しました"), ephemeral=True
            )

    @app_commands.command(name="settime_ctf", description="CTFの終了時間を設定します。")
    @app_commands.describe(
        name="CTF名",
        end_time="終了時間（ISO形式: YYYY-MM-DDTHH:MM:SS または YYYY-MM-DD HH:MM:SS）",
    )
    async def settime_ctf(
        self, interaction: discord.Interaction, name: str, end_time: str
    ) -> None:
        """
        Set the end time for a CTF event.

        Args:
            interaction: Command interaction
            name: CTF name
            end_time: End time in ISO format
        """
        if interaction.guild is None:
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return

        # Check if CTF exists
        ctf_event = get_ctf_event(name, interaction.guild.id)
        if not ctf_event:
            await interaction.response.send_message(
                f"CTF '{name}' が見つかりません。", ephemeral=True
            )
            return

        # Parse end time
        try:
            # Try different datetime formats
            for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"]:
                try:
                    parsed_time = datetime.strptime(end_time, fmt)
                    # Assume UTC if no timezone info
                    if parsed_time.tzinfo is None:
                        parsed_time = parsed_time.replace(tzinfo=UTC)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("Invalid datetime format")

            # Convert to ISO format for database storage
            iso_time = parsed_time.isoformat()

            # Update database
            update_ctf_event(
                name=name,
                guild_id=interaction.guild.id,
                end_time=iso_time,
            )

            await interaction.response.send_message(
                f"CTF '{name}' の終了時間を {parsed_time.strftime('%Y-%m-%d %H:%M:%S UTC')} に設定しました。"
            )

            logger.info(f"Set end time for CTF '{name}' to {iso_time}")

        except ValueError:
            await interaction.response.send_message(
                "無効な時間形式です。以下の形式を使用してください：\n"
                "- YYYY-MM-DDTHH:MM:SS\n"
                "- YYYY-MM-DD HH:MM:SS\n"
                "例: 2024-12-31T23:59:59",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                handle_error(e, "終了時間の設定に失敗しました"), ephemeral=True
            )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        """
        Handle reaction additions for CTF participation.

        Args:
            payload: Reaction event payload
        """
        # Ignore bot reactions
        if payload.user_id == self.bot.user.id:
            return

        # Only handle flag emoji
        if str(payload.emoji) != "🚩":
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        # Check if this is a CTF announcement message
        from ..db.database import fetch_one

        ctf_data = fetch_one(
            "SELECT * FROM ctf_events WHERE announcement_message_id = ? AND guild_id = ? AND is_active = 1",
            (payload.message_id, payload.guild_id),
        )

        if not ctf_data:
            return

        # Get role and member
        role = guild.get_role(ctf_data[3])  # role_id is at index 3
        member = guild.get_member(payload.user_id)

        if not role or not member:
            return

        try:
            # Add role to member
            await member.add_roles(role, reason=f"Joined CTF: {ctf_data[1]}")
            logger.info(f"Added role {role.name} to {member.display_name}")

            # Send confirmation DM
            try:
                await member.send(
                    f"🚩 CTF '{ctf_data[1]}' に参加しました！\n"
                    f"専用チャンネルにアクセスできるようになりました。"
                )
            except discord.Forbidden:
                # Can't send DM, that's okay
                pass

        except discord.Forbidden:
            logger.error(
                f"Failed to add role {role.name} to {member.display_name}: No permission"
            )
        except Exception as e:
            logger.error(f"Error adding role: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        """
        Handle reaction removals for CTF participation.

        Args:
            payload: Reaction event payload
        """
        # Only handle flag emoji
        if str(payload.emoji) != "🚩":
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        # Check if this is a CTF announcement message
        from ..db.database import fetch_one

        ctf_data = fetch_one(
            "SELECT * FROM ctf_events WHERE announcement_message_id = ? AND guild_id = ? AND is_active = 1",
            (payload.message_id, payload.guild_id),
        )

        if not ctf_data:
            return

        # Get role and member
        role = guild.get_role(ctf_data[3])  # role_id is at index 3
        member = guild.get_member(payload.user_id)

        if not role or not member:
            return

        try:
            # Remove role from member
            await member.remove_roles(role, reason=f"Left CTF: {ctf_data[1]}")
            logger.info(f"Removed role {role.name} from {member.display_name}")

        except discord.Forbidden:
            logger.error(
                f"Failed to remove role {role.name} from {member.display_name}: No permission"
            )
        except Exception as e:
            logger.error(f"Error removing role: {e}")

    @tasks.loop(minutes=1)
    async def cleanup_ended_ctfs(self) -> None:
        """
        Periodic task to clean up ended CTF events.
        Runs every minute to check for CTFs that have passed their end time.
        """
        try:
            ended_ctfs = get_ctf_events_to_end()

            for ctf_data in ended_ctfs:
                await self._cleanup_ctf_event(ctf_data)

        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")

    @cleanup_ended_ctfs.before_loop
    async def before_cleanup(self) -> None:
        """Wait until the bot is ready before starting the cleanup task."""
        await self.bot.wait_until_ready()

    async def _cleanup_ctf_event(self, ctf_data: tuple[Any, ...]) -> None:
        """
        Clean up a single CTF event.

        Args:
            ctf_data: CTF event data from database
        """
        try:
            # Extract data from tuple
            (
                ctf_id,
                name,
                guild_id,
                role_id,
                text_channel_id,
                voice_channel_id,
                announcement_message_id,
                end_time,
                is_active,
                created_at,
            ) = ctf_data

            guild = self.bot.get_guild(guild_id)
            if not guild:
                logger.warning(f"Guild {guild_id} not found for CTF cleanup: {name}")
                deactivate_ctf_event(name, guild_id)
                return

            # Delete role
            if role_id:
                role = guild.get_role(role_id)
                if role:
                    try:
                        await role.delete(reason=f"CTF ended: {name}")
                        logger.info(f"Deleted role for CTF: {name}")
                    except discord.Forbidden:
                        logger.error(f"No permission to delete role for CTF: {name}")
                    except Exception as e:
                        logger.error(f"Error deleting role for CTF {name}: {e}")

            # Make text channel public and move to archive
            if text_channel_id:
                text_channel = guild.get_channel(text_channel_id)
                if text_channel and isinstance(text_channel, discord.TextChannel):
                    try:
                        # Make channel public
                        overwrites = text_channel.overwrites
                        overwrites[guild.default_role] = discord.PermissionOverwrite(
                            read_messages=True
                        )
                        await text_channel.edit(
                            overwrites=overwrites, reason=f"CTF ended: {name}"
                        )

                        # Try to find or create archive category
                        archive_category = None
                        for category in guild.categories:
                            if category.name.lower() in [
                                "archive",
                                "archived",
                                "アーカイブ",
                            ]:
                                archive_category = category
                                break

                        if not archive_category:
                            # Create archive category if it doesn't exist
                            try:
                                archive_category = await guild.create_category(
                                    "Archive", reason="CTF archive category"
                                )
                            except discord.Forbidden:
                                logger.warning(
                                    "No permission to create archive category"
                                )

                        # Move channel to archive category
                        if archive_category:
                            await text_channel.edit(
                                category=archive_category, reason=f"CTF ended: {name}"
                            )

                        logger.info(f"Archived text channel for CTF: {name}")

                    except discord.Forbidden:
                        logger.error(
                            f"No permission to modify text channel for CTF: {name}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Error modifying text channel for CTF {name}: {e}"
                        )

            # Delete voice channel
            if voice_channel_id:
                voice_channel = guild.get_channel(voice_channel_id)
                if voice_channel:
                    try:
                        await voice_channel.delete(reason=f"CTF ended: {name}")
                        logger.info(f"Deleted voice channel for CTF: {name}")
                    except discord.Forbidden:
                        logger.error(
                            f"No permission to delete voice channel for CTF: {name}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Error deleting voice channel for CTF {name}: {e}"
                        )

            # Send notification to the text channel if it still exists
            if text_channel_id:
                text_channel = guild.get_channel(text_channel_id)
                if text_channel and isinstance(text_channel, discord.TextChannel):
                    embed = discord.Embed(
                        title=f"🏁 CTF終了: {name}",
                        description=f"CTF '{name}' が終了しました。\n\n"
                        "- ロールが削除されました\n"
                        "- このチャンネルは公開され、アーカイブに移動されました\n"
                        "- ボイスチャンネルは削除されました",
                        color=discord.Color.orange(),
                    )
                    await send_message_safely(text_channel, embed=embed)

            # Deactivate in database
            deactivate_ctf_event(name, guild_id)
            logger.info(f"Completed cleanup for CTF: {name}")

        except Exception as e:
            logger.error(f"Error cleaning up CTF event: {e}")


async def setup(bot: commands.Bot) -> None:
    """
    Add the CTFManagement cog to the bot.

    Args:
        bot: The bot instance
    """
    await bot.add_cog(CTFManagement(bot))
