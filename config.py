"""
Configuration for the Telegram Account Manager.
"""
import os

# --- Telegram Bot (python-telegram-bot) ---
BOT_TOKEN = "8675977036:AAFXwmL0FX-QM1XMykEqr9RsCopwqdDAS5g"  # From @BotFather

# --- Telethon API (my.telegram.org) ---
API_ID = 37927665  # Your API ID (integer)
API_HASH = "6cc390ad7fdf473b9c5df526acfa18e0"

# --- MongoDB ---
MONGO_URI = "mongodb+srv://nexacoders2_db_user:dxYh7QOdHvH6OVdd@cluster0.f4qxcbk.mongodb.net/?appName=Cluster0"
DB_NAME = "telegram_account_manager"

# --- Authorized Users ---
OWNER_ID = 8580367479
ADMIN_IDS = [8580367479, 8694029886, 7684269512]

# --- Join Distribution (percentages) ---
# Mode 1: Always Online,  Mode 2: Last Seen Recently,  Mode 3: Offline after 2 mins
JOIN_MODE_1_PERCENT = 20   # Always online
JOIN_MODE_2_PERCENT = 40   # Last seen recently
JOIN_MODE_3_PERCENT = 40   # Offline after 2 mins

# --- Timing ---
ONLINE_KEEPALIVE_INTERVAL = 45  # seconds between keep-alive pings
OFFLINE_AFTER_SECONDS = 120     # 2 minutes before going offline (Mode 3)

# --- Files ---
NAME_FILE = "name.txt"
