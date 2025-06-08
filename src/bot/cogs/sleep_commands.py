"""
Sleep tracking commands cog for the CTF Discord bot.
Contains commands for tracking sleep patterns (/gn, /gm, etc.).
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
from typing import Optional

from ..db.database import (
    create_sleep_records_table_if_not_exists,
    insert_sleep_record,
    get_sleep_record,
    delete_sleep_record,
    get_sleep_records_by_period,
    get_sleep_statistics
)
from ..utils.helpers import handle_error


class SleepCommands(commands.Cog):
    """Cog for sleep tracking commands."""

    def __init__(self, bot: commands.Bot):
        """
        Initialize the SleepCommands cog.

        Args:
            bot: The bot instance
        """
        self.bot = bot
        # Create sleep records table on initialization
        create_sleep_records_table_if_not_exists()

    @app_commands.command(name="gn", description="記録就寝時刻 (Good Night)")
    @app_commands.describe(
        time="就寝時刻 (HH:MM形式、省略時は現在時刻)",
        date="日付 (YYYY-MM-DD形式、省略時は今日)"
    )
    async def good_night(
        self, 
        interaction: discord.Interaction, 
        time: Optional[str] = None,
        date: Optional[str] = None
    ):
        """
        Record bedtime.
        
        Args:
            interaction: Discord interaction
            time: Bedtime in HH:MM format (optional, defaults to current time)
            date: Date in YYYY-MM-DD format (optional, defaults to today)
        """
        try:
            user_id = interaction.user.id
            
            # Parse date
            if date:
                try:
                    record_date = datetime.strptime(date, "%Y-%m-%d").date()
                except ValueError:
                    await interaction.response.send_message(
                        "❌ 日付の形式が正しくありません。YYYY-MM-DD形式で入力してください。",
                        ephemeral=True
                    )
                    return
            else:
                record_date = datetime.now().date()
            
            # Parse time
            if time:
                try:
                    time_obj = datetime.strptime(time, "%H:%M").time()
                    bedtime = datetime.combine(record_date, time_obj)
                except ValueError:
                    await interaction.response.send_message(
                        "❌ 時刻の形式が正しくありません。HH:MM形式で入力してください。",
                        ephemeral=True
                    )
                    return
            else:
                bedtime = datetime.now()
                # If it's past midnight, record for previous day
                if bedtime.hour < 12:
                    record_date = (bedtime - timedelta(days=1)).date()
                    bedtime = bedtime.replace(
                        year=record_date.year,
                        month=record_date.month,
                        day=record_date.day
                    )
            
            # Insert sleep record
            result = insert_sleep_record(
                user_id=user_id,
                date=record_date.strftime("%Y-%m-%d"),
                bedtime=bedtime.strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Create embed response
            embed = discord.Embed(
                title="🌙 おやすみなさい！",
                description=f"就寝時刻を記録しました",
                color=discord.Color.blue()
            )
            embed.add_field(
                name="日付", 
                value=record_date.strftime("%Y年%m月%d日"), 
                inline=True
            )
            embed.add_field(
                name="就寝時刻", 
                value=bedtime.strftime("%H:%M"), 
                inline=True
            )
            embed.set_footer(text="良い夢を！")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="gm", description="記録起床時刻 (Good Morning)")
    @app_commands.describe(
        time="起床時刻 (HH:MM形式、省略時は現在時刻)",
        date="日付 (YYYY-MM-DD形式、省略時は今日)"
    )
    async def good_morning(
        self, 
        interaction: discord.Interaction, 
        time: Optional[str] = None,
        date: Optional[str] = None
    ):
        """
        Record wakeup time.
        
        Args:
            interaction: Discord interaction
            time: Wakeup time in HH:MM format (optional, defaults to current time)
            date: Date in YYYY-MM-DD format (optional, defaults to today)
        """
        try:
            user_id = interaction.user.id
            
            # Parse date
            if date:
                try:
                    record_date = datetime.strptime(date, "%Y-%m-%d").date()
                except ValueError:
                    await interaction.response.send_message(
                        "❌ 日付の形式が正しくありません。YYYY-MM-DD形式で入力してください。",
                        ephemeral=True
                    )
                    return
            else:
                record_date = datetime.now().date()
            
            # Parse time
            if time:
                try:
                    time_obj = datetime.strptime(time, "%H:%M").time()
                    wakeup_time = datetime.combine(record_date, time_obj)
                except ValueError:
                    await interaction.response.send_message(
                        "❌ 時刻の形式が正しくありません。HH:MM形式で入力してください。",
                        ephemeral=True
                    )
                    return
            else:
                wakeup_time = datetime.now()
                record_date = wakeup_time.date()
            
            # Insert sleep record
            result = insert_sleep_record(
                user_id=user_id,
                date=record_date.strftime("%Y-%m-%d"),
                wakeup_time=wakeup_time.strftime("%Y-%m-%d %H:%M:%S")
            )
            
            # Get updated record to show sleep duration
            record = get_sleep_record(user_id, record_date.strftime("%Y-%m-%d"))
            
            # Create embed response
            embed = discord.Embed(
                title="☀️ おはようございます！",
                description=f"起床時刻を記録しました",
                color=discord.Color.gold()
            )
            embed.add_field(
                name="日付", 
                value=record_date.strftime("%Y年%m月%d日"), 
                inline=True
            )
            embed.add_field(
                name="起床時刻", 
                value=wakeup_time.strftime("%H:%M"), 
                inline=True
            )
            
            # Show sleep duration if both bedtime and wakeup time are recorded
            if record and record[5]:  # sleep_duration
                hours = record[5] // 60
                minutes = record[5] % 60
                embed.add_field(
                    name="睡眠時間", 
                    value=f"{hours}時間{minutes}分", 
                    inline=True
                )
            
            embed.set_footer(text="今日も一日頑張りましょう！")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="sleep-list", description="睡眠記録の一覧表示")
    @app_commands.describe(
        days="表示する日数 (デフォルト: 7日)"
    )
    async def sleep_list(
        self, 
        interaction: discord.Interaction, 
        days: Optional[int] = 7
    ):
        """
        Show sleep records list.
        
        Args:
            interaction: Discord interaction
            days: Number of days to show (default: 7)
        """
        try:
            user_id = interaction.user.id
            
            # Validate days parameter
            if days < 1 or days > 30:
                await interaction.response.send_message(
                    "❌ 日数は1〜30の範囲で指定してください。",
                    ephemeral=True
                )
                return
            
            # Calculate date range
            end_date = datetime.now().date()
            start_date = end_date - timedelta(days=days-1)
            
            # Get sleep records
            records = get_sleep_records_by_period(
                user_id, 
                start_date.strftime("%Y-%m-%d"), 
                end_date.strftime("%Y-%m-%d")
            )
            
            # Create embed
            embed = discord.Embed(
                title=f"📊 睡眠記録 (過去{days}日間)",
                color=discord.Color.green()
            )
            
            if not records:
                embed.description = "記録がありません。"
            else:
                record_text = ""
                for record in reversed(records):  # Show newest first
                    date_str = record[2]
                    bedtime = record[3]
                    wakeup_time = record[4]
                    duration = record[5]
                    
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                    date_display = date_obj.strftime("%m/%d")
                    
                    bedtime_display = "未記録"
                    if bedtime:
                        bedtime_obj = datetime.fromisoformat(bedtime)
                        bedtime_display = bedtime_obj.strftime("%H:%M")
                    
                    wakeup_display = "未記録"
                    if wakeup_time:
                        wakeup_obj = datetime.fromisoformat(wakeup_time)
                        wakeup_display = wakeup_obj.strftime("%H:%M")
                    
                    duration_display = "未計算"
                    if duration:
                        hours = duration // 60
                        minutes = duration % 60
                        duration_display = f"{hours}h{minutes}m"
                    
                    record_text += f"**{date_display}** 🛏️{bedtime_display} ⏰{wakeup_display} 💤{duration_display}\n"
                
                embed.description = record_text
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="sleep-edit", description="睡眠記録の編集")
    @app_commands.describe(
        date="編集する日付 (YYYY-MM-DD形式)",
        bedtime="就寝時刻 (HH:MM形式、省略時は変更なし)",
        wakeup_time="起床時刻 (HH:MM形式、省略時は変更なし)"
    )
    async def sleep_edit(
        self, 
        interaction: discord.Interaction, 
        date: str,
        bedtime: Optional[str] = None,
        wakeup_time: Optional[str] = None
    ):
        """
        Edit existing sleep record.
        
        Args:
            interaction: Discord interaction
            date: Date to edit in YYYY-MM-DD format
            bedtime: New bedtime in HH:MM format (optional)
            wakeup_time: New wakeup time in HH:MM format (optional)
        """
        try:
            user_id = interaction.user.id
            
            # Validate date format
            try:
                record_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                await interaction.response.send_message(
                    "❌ 日付の形式が正しくありません。YYYY-MM-DD形式で入力してください。",
                    ephemeral=True
                )
                return
            
            # Check if record exists
            existing_record = get_sleep_record(user_id, date)
            if not existing_record:
                await interaction.response.send_message(
                    f"❌ {date}の睡眠記録が見つかりません。",
                    ephemeral=True
                )
                return
            
            # Parse and validate times
            bedtime_str = None
            wakeup_str = None
            
            if bedtime:
                try:
                    time_obj = datetime.strptime(bedtime, "%H:%M").time()
                    bedtime_dt = datetime.combine(record_date, time_obj)
                    bedtime_str = bedtime_dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    await interaction.response.send_message(
                        "❌ 就寝時刻の形式が正しくありません。HH:MM形式で入力してください。",
                        ephemeral=True
                    )
                    return
            
            if wakeup_time:
                try:
                    time_obj = datetime.strptime(wakeup_time, "%H:%M").time()
                    wakeup_dt = datetime.combine(record_date, time_obj)
                    wakeup_str = wakeup_dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    await interaction.response.send_message(
                        "❌ 起床時刻の形式が正しくありません。HH:MM形式で入力してください。",
                        ephemeral=True
                    )
                    return
            
            # Update record
            result = insert_sleep_record(
                user_id=user_id,
                date=date,
                bedtime=bedtime_str,
                wakeup_time=wakeup_str
            )
            
            # Get updated record
            updated_record = get_sleep_record(user_id, date)
            
            # Create embed response
            embed = discord.Embed(
                title="✏️ 睡眠記録を編集しました",
                color=discord.Color.orange()
            )
            embed.add_field(
                name="日付", 
                value=record_date.strftime("%Y年%m月%d日"), 
                inline=False
            )
            
            if updated_record[3]:  # bedtime
                bedtime_obj = datetime.fromisoformat(updated_record[3])
                embed.add_field(
                    name="就寝時刻", 
                    value=bedtime_obj.strftime("%H:%M"), 
                    inline=True
                )
            
            if updated_record[4]:  # wakeup_time
                wakeup_obj = datetime.fromisoformat(updated_record[4])
                embed.add_field(
                    name="起床時刻", 
                    value=wakeup_obj.strftime("%H:%M"), 
                    inline=True
                )
            
            if updated_record[5]:  # sleep_duration
                hours = updated_record[5] // 60
                minutes = updated_record[5] % 60
                embed.add_field(
                    name="睡眠時間", 
                    value=f"{hours}時間{minutes}分", 
                    inline=True
                )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await handle_error(interaction, e)

    @app_commands.command(name="sleep-delete", description="睡眠記録の削除")
    @app_commands.describe(
        date="削除する日付 (YYYY-MM-DD形式)"
    )
    async def sleep_delete(
        self, 
        interaction: discord.Interaction, 
        date: str
    ):
        """
        Delete sleep record.
        
        Args:
            interaction: Discord interaction
            date: Date to delete in YYYY-MM-DD format
        """
        try:
            user_id = interaction.user.id
            
            # Validate date format
            try:
                record_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                await interaction.response.send_message(
                    "❌ 日付の形式が正しくありません。YYYY-MM-DD形式で入力してください。",
                    ephemeral=True
                )
                return
            
            # Check if record exists
            existing_record = get_sleep_record(user_id, date)
            if not existing_record:
                await interaction.response.send_message(
                    f"❌ {date}の睡眠記録が見つかりません。",
                    ephemeral=True
                )
                return
            
            # Create confirmation view
            class ConfirmView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=30)
                    self.confirmed = False
                
                @discord.ui.button(label="削除", style=discord.ButtonStyle.danger, emoji="🗑️")
                async def confirm_delete(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                    if button_interaction.user.id != user_id:
                        await button_interaction.response.send_message(
                            "❌ この操作を実行する権限がありません。",
                            ephemeral=True
                        )
                        return
                    
                    # Delete the record
                    result = delete_sleep_record(user_id, date)
                    
                    embed = discord.Embed(
                        title="🗑️ 睡眠記録を削除しました",
                        description=f"{record_date.strftime('%Y年%m月%d日')}の記録を削除しました。",
                        color=discord.Color.red()
                    )
                    
                    await button_interaction.response.edit_message(embed=embed, view=None)
                    self.confirmed = True
                    self.stop()
                
                @discord.ui.button(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="❌")
                async def cancel_delete(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                    if button_interaction.user.id != user_id:
                        await button_interaction.response.send_message(
                            "❌ この操作を実行する権限がありません。",
                            ephemeral=True
                        )
                        return
                    
                    embed = discord.Embed(
                        title="キャンセルしました",
                        description="睡眠記録の削除をキャンセルしました。",
                        color=discord.Color.grey()
                    )
                    
                    await button_interaction.response.edit_message(embed=embed, view=None)
                    self.stop()
            
            # Create confirmation embed
            embed = discord.Embed(
                title="⚠️ 睡眠記録の削除確認",
                description=f"{record_date.strftime('%Y年%m月%d日')}の睡眠記録を削除しますか？",
                color=discord.Color.yellow()
            )
            
            # Show current record details
            if existing_record[3]:  # bedtime
                bedtime_obj = datetime.fromisoformat(existing_record[3])
                embed.add_field(
                    name="就寝時刻", 
                    value=bedtime_obj.strftime("%H:%M"), 
                    inline=True
                )
            
            if existing_record[4]:  # wakeup_time
                wakeup_obj = datetime.fromisoformat(existing_record[4])
                embed.add_field(
                    name="起床時刻", 
                    value=wakeup_obj.strftime("%H:%M"), 
                    inline=True
                )
            
            if existing_record[5]:  # sleep_duration
                hours = existing_record[5] // 60
                minutes = existing_record[5] % 60
                embed.add_field(
                    name="睡眠時間", 
                    value=f"{hours}時間{minutes}分", 
                    inline=True
                )
            
            view = ConfirmView()
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            
        except Exception as e:
            await handle_error(interaction, e)


    @app_commands.command(name="sleep-graph", description="睡眠パターンのグラフと統計を表示")
    @app_commands.describe(
        period="表示期間 (week: 週単位, month: 月単位)",
        date="基準日付 (YYYY-MM-DD形式、省略時は今日)"
    )
    @app_commands.choices(period=[
        app_commands.Choice(name="週単位", value="week"),
        app_commands.Choice(name="月単位", value="month")
    ])
    async def sleep_graph(
        self, 
        interaction: discord.Interaction, 
        period: str,
        date: Optional[str] = None
    ):
        """
        Show sleep pattern graph and statistics.
        
        Args:
            interaction: Discord interaction
            period: Display period (week or month)
            date: Reference date in YYYY-MM-DD format (optional, defaults to today)
        """
        try:
            from ..utils.sleep_graphs import (
                generate_weekly_sleep_graph, 
                generate_monthly_sleep_graph,
                format_duration_text
            )
            
            user_id = interaction.user.id
            
            # Parse reference date
            if date:
                try:
                    ref_date = datetime.strptime(date, "%Y-%m-%d")
                except ValueError:
                    await interaction.response.send_message(
                        "❌ 日付の形式が正しくありません。YYYY-MM-DD形式で入力してください。",
                        ephemeral=True
                    )
                    return
            else:
                ref_date = datetime.now()
            
            # Defer response as graph generation might take time
            await interaction.response.defer()
            
            if period == "week":
                # Calculate start of week (Monday)
                days_since_monday = ref_date.weekday()
                week_start = ref_date - timedelta(days=days_since_monday)
                week_end = week_start + timedelta(days=6)
                
                # Generate graph
                graph_path = generate_weekly_sleep_graph(user_id, week_start.strftime("%Y-%m-%d"))
                
                if not graph_path:
                    embed = discord.Embed(
                        title="📊 週間睡眠グラフ",
                        description="この期間の睡眠記録がありません。",
                        color=discord.Color.grey()
                    )
                    await interaction.followup.send(embed=embed)
                    return
                
                # Get statistics
                stats = get_sleep_statistics(
                    user_id, 
                    week_start.strftime("%Y-%m-%d"), 
                    week_end.strftime("%Y-%m-%d")
                )
                
                # Create embed
                embed = discord.Embed(
                    title="📊 週間睡眠グラフ",
                    description=f"{week_start.strftime('%Y年%m月%d日')} 〜 {week_end.strftime('%m月%d日')}",
                    color=discord.Color.blue()
                )
                
            else:  # month
                year = ref_date.year
                month = ref_date.month
                
                # Generate graph
                graph_path = generate_monthly_sleep_graph(user_id, year, month)
                
                if not graph_path:
                    embed = discord.Embed(
                        title="📊 月間睡眠グラフ",
                        description="この期間の睡眠記録がありません。",
                        color=discord.Color.grey()
                    )
                    await interaction.followup.send(embed=embed)
                    return
                
                # Calculate month date range
                month_start = datetime(year, month, 1)
                if month == 12:
                    month_end = datetime(year + 1, 1, 1) - timedelta(days=1)
                else:
                    month_end = datetime(year, month + 1, 1) - timedelta(days=1)
                
                # Get statistics
                stats = get_sleep_statistics(
                    user_id, 
                    month_start.strftime("%Y-%m-%d"), 
                    month_end.strftime("%Y-%m-%d")
                )
                
                # Create embed
                embed = discord.Embed(
                    title="📊 月間睡眠グラフ",
                    description=f"{year}年{month}月",
                    color=discord.Color.green()
                )
            
            # Add statistics to embed
            if stats["total_records"] > 0:
                embed.add_field(
                    name="📈 統計情報",
                    value=f"記録日数: {stats['total_records']}日",
                    inline=False
                )
                
                if stats["average_sleep_duration"] > 0:
                    embed.add_field(
                        name="⏰ 平均睡眠時間",
                        value=format_duration_text(stats["average_sleep_duration"]),
                        inline=True
                    )
                    
                    embed.add_field(
                        name="💤 総睡眠時間",
                        value=format_duration_text(stats["total_sleep_time"]),
                        inline=True
                    )
                    
                    embed.add_field(
                        name="🔝 最長睡眠",
                        value=format_duration_text(stats["longest_sleep"]),
                        inline=True
                    )
                    
                    embed.add_field(
                        name="🔻 最短睡眠",
                        value=format_duration_text(stats["shortest_sleep"]),
                        inline=True
                    )
                    
                    # Sleep quality assessment
                    avg_hours = stats["average_sleep_duration"] / 60
                    if avg_hours >= 7:
                        quality = "😴 良好"
                        quality_color = discord.Color.green()
                    elif avg_hours >= 6:
                        quality = "😐 普通"
                        quality_color = discord.Color.yellow()
                    else:
                        quality = "😵 不足"
                        quality_color = discord.Color.red()
                    
                    embed.add_field(
                        name="🎯 睡眠の質",
                        value=quality,
                        inline=True
                    )
                    embed.color = quality_color
            
            # Add graph image
            file = discord.File(graph_path, filename="sleep_graph.png")
            embed.set_image(url="attachment://sleep_graph.png")
            
            # Add footer
            embed.set_footer(text="💡 理想的な睡眠時間は7-9時間です")
            
            await interaction.followup.send(embed=embed, file=file)
            
            # Clean up temporary file
            try:
                os.remove(graph_path)
            except:
                pass
                
        except Exception as e:
            await handle_error(interaction, e)

async def setup(bot: commands.Bot):
    """
    Add the SleepCommands cog to the bot.

    Args:
        bot: The bot instance
    """
    await bot.add_cog(SleepCommands(bot))
