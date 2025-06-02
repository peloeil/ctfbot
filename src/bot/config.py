"""
Configuration module for the CTF Discord bot.
Centralizes all configuration settings and constants.
"""
import os
from datetime import timezone, timedelta
from dotenv import load_dotenv

# Load environment variables once
load_dotenv()

# Bot configuration
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
COMMAND_PREFIX = "!"
BOT_CHANNEL_ID = int(os.getenv("BOT_CHANNEL_ID") or "0")

# Database configuration
DATABASE_NAME = "alpaca.db"

# Timezone configuration
JST = timezone(timedelta(hours=+9), "JST")

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
