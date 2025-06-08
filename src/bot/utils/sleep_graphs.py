"""
Sleep graph generation utilities for the CTF Discord bot.
Generates sleep pattern visualizations using matplotlib.
"""

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import io
import os

from ..db.database import get_sleep_records_by_period


# Configure matplotlib for Japanese text
plt.rcParams['font.family'] = ['DejaVu Sans', 'Hiragino Sans', 'Yu Gothic', 'Meiryo', 'Takao', 'IPAexGothic', 'IPAPGothic', 'VL PGothic', 'Noto Sans CJK JP']
plt.rcParams['axes.unicode_minus'] = False


def setup_japanese_font():
    """Setup Japanese font for matplotlib if available."""
    try:
        # Try to find a Japanese font
        japanese_fonts = [
            'Hiragino Sans',
            'Yu Gothic',
            'Meiryo',
            'Takao',
            'IPAexGothic',
            'IPAPGothic',
            'VL PGothic',
            'Noto Sans CJK JP'
        ]
        
        available_fonts = [f.name for f in font_manager.fontManager.ttflist]
        
        for font in japanese_fonts:
            if font in available_fonts:
                plt.rcParams['font.family'] = font
                break
        else:
            # Fallback to default
            plt.rcParams['font.family'] = 'DejaVu Sans'
            
    except Exception:
        # Use default font if Japanese font setup fails
        plt.rcParams['font.family'] = 'DejaVu Sans'


def generate_weekly_sleep_graph(user_id: int, start_date: str) -> Optional[str]:
    """
    Generate a weekly sleep pattern graph.
    
    Args:
        user_id: Discord user ID
        start_date: Start date in 'YYYY-MM-DD' format
    
    Returns:
        Path to the generated graph image file, or None if no data
    """
    try:
        setup_japanese_font()
        
        # Calculate end date (7 days from start)
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = start_dt + timedelta(days=6)
        end_date = end_dt.strftime("%Y-%m-%d")
        
        # Get sleep records
        records = get_sleep_records_by_period(user_id, start_date, end_date)
        
        if not records:
            return None
        
        # Prepare data
        dates = []
        bedtimes = []
        wakeup_times = []
        sleep_durations = []
        
        # Create a complete date range
        current_date = start_dt
        for i in range(7):
            date_str = current_date.strftime("%Y-%m-%d")
            dates.append(current_date)
            
            # Find record for this date
            record = next((r for r in records if r[2] == date_str), None)
            
            if record and record[3] and record[4]:  # bedtime and wakeup_time exist
                bedtime_dt = datetime.fromisoformat(record[3])
                wakeup_dt = datetime.fromisoformat(record[4])
                
                # Convert to hours for plotting
                bedtime_hour = bedtime_dt.hour + bedtime_dt.minute / 60
                wakeup_hour = wakeup_dt.hour + wakeup_dt.minute / 60
                
                # Adjust bedtime if it's late (after 18:00, consider as previous day)
                if bedtime_hour >= 18:
                    bedtime_hour -= 24
                
                bedtimes.append(bedtime_hour)
                wakeup_times.append(wakeup_hour)
                sleep_durations.append(record[5] / 60 if record[5] else 0)  # Convert to hours
            else:
                bedtimes.append(None)
                wakeup_times.append(None)
                sleep_durations.append(0)
            
            current_date += timedelta(days=1)
        
        # Create the plot
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
        
        # Plot 1: Sleep and wake times
        ax1.set_title('週間睡眠パターン', fontsize=16, fontweight='bold', pad=20)
        
        # Plot bedtimes and wakeup times
        valid_dates = [d for i, d in enumerate(dates) if bedtimes[i] is not None]
        valid_bedtimes = [b for b in bedtimes if b is not None]
        valid_wakeup_times = [w for i, w in enumerate(wakeup_times) if bedtimes[i] is not None]
        
        if valid_dates:
            ax1.plot(valid_dates, valid_bedtimes, 'o-', color='navy', linewidth=2, 
                    markersize=8, label='就寝時刻', alpha=0.8)
            ax1.plot(valid_dates, valid_wakeup_times, 'o-', color='orange', linewidth=2, 
                    markersize=8, label='起床時刻', alpha=0.8)
        
        # Format x-axis
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax1.xaxis.set_major_locator(mdates.DayLocator())
        
        # Format y-axis (hours)
        ax1.set_ylim(-6, 12)
        ax1.set_yticks(range(-6, 13, 2))
        ax1.set_yticklabels([f'{h:02d}:00' if h >= 0 else f'{24+h:02d}:00' for h in range(-6, 13, 2)])
        
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc='upper right')
        ax1.set_ylabel('時刻', fontsize=12)
        
        # Add horizontal lines for reference
        ax1.axhline(y=0, color='lightblue', linestyle='--', alpha=0.5, label='0:00')
        ax1.axhline(y=6, color='lightgreen', linestyle='--', alpha=0.5, label='6:00')
        
        # Plot 2: Sleep duration
        ax2.set_title('睡眠時間', fontsize=14, fontweight='bold', pad=20)
        
        colors = ['lightcoral' if d < 6 else 'lightgreen' if d < 8 else 'lightblue' for d in sleep_durations]
        bars = ax2.bar(dates, sleep_durations, color=colors, alpha=0.7, edgecolor='black', linewidth=1)
        
        # Add value labels on bars
        for i, (bar, duration) in enumerate(zip(bars, sleep_durations)):
            if duration > 0:
                ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                        f'{duration:.1f}h', ha='center', va='bottom', fontsize=10)
        
        # Format x-axis
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax2.xaxis.set_major_locator(mdates.DayLocator())
        
        ax2.set_ylim(0, max(12, max(sleep_durations) + 1) if sleep_durations else 12)
        ax2.set_ylabel('時間', fontsize=12)
        ax2.grid(True, alpha=0.3, axis='y')
        
        # Add reference lines
        ax2.axhline(y=6, color='red', linestyle='--', alpha=0.5, label='6時間')
        ax2.axhline(y=8, color='green', linestyle='--', alpha=0.5, label='8時間')
        ax2.legend(loc='upper right')
        
        # Rotate x-axis labels
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
        
        plt.tight_layout()
        
        # Save the plot
        filename = f"sleep_weekly_{user_id}_{start_date}.png"
        filepath = f"/tmp/{filename}"
        plt.savefig(filepath, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        
        return filepath
        
    except Exception as e:
        print(f"Error generating weekly graph: {e}")
        return None


def generate_monthly_sleep_graph(user_id: int, year: int, month: int) -> Optional[str]:
    """
    Generate a monthly sleep pattern graph.
    
    Args:
        user_id: Discord user ID
        year: Year
        month: Month (1-12)
    
    Returns:
        Path to the generated graph image file, or None if no data
    """
    try:
        setup_japanese_font()
        
        # Calculate date range for the month
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1) - timedelta(days=1)
        
        # Get sleep records
        records = get_sleep_records_by_period(
            user_id, 
            start_date.strftime("%Y-%m-%d"), 
            end_date.strftime("%Y-%m-%d")
        )
        
        if not records:
            return None
        
        # Prepare data
        dates = []
        sleep_durations = []
        avg_bedtimes = []
        avg_wakeup_times = []
        
        # Create a complete date range for the month
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            dates.append(current_date)
            
            # Find record for this date
            record = next((r for r in records if r[2] == date_str), None)
            
            if record and record[5]:  # sleep_duration exists
                sleep_durations.append(record[5] / 60)  # Convert to hours
                
                if record[3]:  # bedtime
                    bedtime_dt = datetime.fromisoformat(record[3])
                    bedtime_hour = bedtime_dt.hour + bedtime_dt.minute / 60
                    if bedtime_hour >= 18:
                        bedtime_hour -= 24
                    avg_bedtimes.append(bedtime_hour)
                else:
                    avg_bedtimes.append(None)
                
                if record[4]:  # wakeup_time
                    wakeup_dt = datetime.fromisoformat(record[4])
                    wakeup_hour = wakeup_dt.hour + wakeup_dt.minute / 60
                    avg_wakeup_times.append(wakeup_hour)
                else:
                    avg_wakeup_times.append(None)
            else:
                sleep_durations.append(0)
                avg_bedtimes.append(None)
                avg_wakeup_times.append(None)
            
            current_date += timedelta(days=1)
        
        # Create the plot
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10))
        
        # Plot 1: Daily sleep duration
        ax1.set_title(f'{year}年{month}月 睡眠時間', fontsize=16, fontweight='bold', pad=20)
        
        colors = ['lightcoral' if d < 6 else 'lightgreen' if d < 8 else 'lightblue' for d in sleep_durations]
        bars = ax1.bar(dates, sleep_durations, color=colors, alpha=0.7, edgecolor='black', linewidth=0.5)
        
        # Format x-axis
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d'))
        ax1.xaxis.set_major_locator(mdates.DayLocator(interval=2))
        
        ax1.set_ylim(0, max(12, max(sleep_durations) + 1) if sleep_durations else 12)
        ax1.set_ylabel('睡眠時間 (時間)', fontsize=12)
        ax1.grid(True, alpha=0.3, axis='y')
        
        # Add reference lines
        ax1.axhline(y=6, color='red', linestyle='--', alpha=0.5, label='6時間')
        ax1.axhline(y=8, color='green', linestyle='--', alpha=0.5, label='8時間')
        ax1.legend(loc='upper right')
        
        # Plot 2: Sleep and wake times trend
        ax2.set_title('就寝・起床時刻の推移', fontsize=14, fontweight='bold', pad=20)
        
        # Filter valid data points
        valid_indices = [i for i, (b, w) in enumerate(zip(avg_bedtimes, avg_wakeup_times)) 
                        if b is not None and w is not None]
        
        if valid_indices:
            valid_dates_trend = [dates[i] for i in valid_indices]
            valid_bedtimes_trend = [avg_bedtimes[i] for i in valid_indices]
            valid_wakeup_trend = [avg_wakeup_times[i] for i in valid_indices]
            
            ax2.plot(valid_dates_trend, valid_bedtimes_trend, 'o-', color='navy', 
                    linewidth=1, markersize=4, label='就寝時刻', alpha=0.8)
            ax2.plot(valid_dates_trend, valid_wakeup_trend, 'o-', color='orange', 
                    linewidth=1, markersize=4, label='起床時刻', alpha=0.8)
        
        # Format axes
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%d'))
        ax2.xaxis.set_major_locator(mdates.DayLocator(interval=2))
        
        ax2.set_ylim(-6, 12)
        ax2.set_yticks(range(-6, 13, 2))
        ax2.set_yticklabels([f'{h:02d}:00' if h >= 0 else f'{24+h:02d}:00' for h in range(-6, 13, 2)])
        
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='upper right')
        ax2.set_ylabel('時刻', fontsize=12)
        ax2.set_xlabel('日', fontsize=12)
        
        # Rotate x-axis labels
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
        
        plt.tight_layout()
        
        # Save the plot
        filename = f"sleep_monthly_{user_id}_{year}_{month:02d}.png"
        filepath = f"/tmp/{filename}"
        plt.savefig(filepath, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        
        return filepath
        
    except Exception as e:
        print(f"Error generating monthly graph: {e}")
        return None


def format_duration_text(minutes: float) -> str:
    """
    Format duration in minutes to human-readable text.
    
    Args:
        minutes: Duration in minutes
    
    Returns:
        Formatted duration string
    """
    if minutes == 0:
        return "0分"
    
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    
    if hours > 0 and mins > 0:
        return f"{hours}時間{mins}分"
    elif hours > 0:
        return f"{hours}時間"
    else:
        return f"{mins}分"

