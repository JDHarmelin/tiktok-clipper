"""Loads environment variables and defines constants."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

# Telegram
# Optional now: only bot.py (the old Telegram trigger) needs it
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

# Price per million tokens (input, output), used for the cost line in reports
MODEL_PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}

# Whisper
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

# TikTok
TIKTOK_COOKIES_PATH = os.getenv("TIKTOK_COOKIES_PATH", "./cookies.txt")

# Multi-account support: "name:cookiefile,name2:cookiefile2"
# Falls back to default:TIKTOK_COOKIES_PATH if not set
_raw_accounts = os.getenv("TIKTOK_ACCOUNTS", "")
TIKTOK_ACCOUNTS: dict[str, str] = {}
if _raw_accounts.strip():
    for entry in _raw_accounts.split(","):
        entry = entry.strip()
        if ":" in entry:
            name, path = entry.split(":", 1)
            TIKTOK_ACCOUNTS[name.strip()] = path.strip()
if not TIKTOK_ACCOUNTS:
    TIKTOK_ACCOUNTS["default"] = TIKTOK_COOKIES_PATH

# Pipeline
MAX_CLIPS = int(os.getenv("MAX_CLIPS_PER_VIDEO", "10"))
MIN_CLIP_DURATION = int(os.getenv("MIN_CLIP_DURATION", "20"))
MAX_CLIP_DURATION = int(os.getenv("MAX_CLIP_DURATION", "90"))
OUTPUT_WIDTH = int(os.getenv("OUTPUT_WIDTH", "1080"))
OUTPUT_HEIGHT = int(os.getenv("OUTPUT_HEIGHT", "1920"))

# Stream mode (watcher.py)
# A stream counts as GTA 6 when its title or category contains one of these
GAME_KEYWORDS = [k.strip() for k in os.getenv(
    "GAME_KEYWORDS", "Grand Theft Auto VI,GTA VI,GTA 6,GTA6,GTAVI"
).split(",") if k.strip()]
SEGMENT_SECONDS = int(os.getenv("SEGMENT_SECONDS", "900"))        # VODs are processed in 15 min chunks
# Stream clip layout when no facecam box is set: "zoom" (default) or "fit"
STREAM_LAYOUT = os.getenv("STREAM_LAYOUT", "zoom")
# Your own account handle, shown under the clip in the zoom layout (blank = off)
OUR_HANDLE = os.getenv("OUR_HANDLE", "")
LIVE_RECORD_SECONDS = int(os.getenv("LIVE_RECORD_SECONDS", "600")) # each live pass records 10 min
CLIPS_PER_SEGMENT = int(os.getenv("CLIPS_PER_SEGMENT", "2"))
SEGMENTS_PER_RUN = int(os.getenv("SEGMENTS_PER_RUN", "4"))         # VOD chunks per streamer per pass
POLL_MINUTES = int(os.getenv("POLL_MINUTES", "10"))
MAX_POSTS_PER_ACCOUNT_PER_DAY = int(os.getenv("MAX_POSTS_PER_ACCOUNT_PER_DAY", "8"))
MIN_MINUTES_BETWEEN_POSTS = int(os.getenv("MIN_MINUTES_BETWEEN_POSTS", "45"))

# Directories
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / os.getenv("DOWNLOAD_DIR", "downloads")
CLIPS_DIR = BASE_DIR / os.getenv("CLIPS_DIR", "clips")
SUBTITLES_DIR = BASE_DIR / os.getenv("SUBTITLES_DIR", "subtitles")
GAMEPLAY_DIR = BASE_DIR / os.getenv("GAMEPLAY_DIR", "gameplay")

# Create dirs
DB_PATH = BASE_DIR / os.getenv("DB_PATH", "clipper.db")

for d in [DOWNLOAD_DIR, CLIPS_DIR, SUBTITLES_DIR, GAMEPLAY_DIR, BASE_DIR / "logs"]:
    d.mkdir(exist_ok=True)
