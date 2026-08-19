import os
from dotenv import load_dotenv

# Load local .env if available
load_dotenv()

# --- Telegram API Credentials ---
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Assistant / Userbot Pyrogram String Session (Required for PyTgCalls Voice Chat)
ASSISTANT_SESSION = os.getenv("ASSISTANT_SESSION", os.getenv("SESSION_STRING", ""))

# Admin User IDs (Comma-separated in environment, e.g. "12345678,87654321")
admin_list = os.getenv("ADMIN_USERS", "")
ADMIN_USERS = [int(x.strip()) for x in admin_list.split(",") if x.strip().isdigit()]

# Spotify Credentials (Optional / Fallback)
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID", "")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET", "")

# --- File, Cache & Image Store Configuration ---
# Define Base Directory dynamically based on where config.py is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define specific paths based on the original structure
BG_DIR = os.path.join(BASE_DIR, "user_backgrounds")
CACHE_DIR = os.path.join(BASE_DIR, "spotify_tokens")
CREDS_FILE = os.path.join(BASE_DIR, "user_credentials.json")
FONT_FILE = os.path.join(BASE_DIR, "font.ttf")
PFP_DIR = os.path.join(BASE_DIR, "user_pfps")
OPACITY_FILE = os.path.join(BASE_DIR, "user_opacity.json")

# Automatically create the directories so plugins don't crash when saving files
os.makedirs(PFP_DIR, exist_ok=True)
os.makedirs(BG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
