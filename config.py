"""Loads environment variables and defines constants."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)

# Telegram
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))

# Anthropic
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = "claude-sonnet-4-20250514"

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

# Directories
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / os.getenv("DOWNLOAD_DIR", "downloads")
CLIPS_DIR = BASE_DIR / os.getenv("CLIPS_DIR", "clips")
SUBTITLES_DIR = BASE_DIR / os.getenv("SUBTITLES_DIR", "subtitles")
GAMEPLAY_DIR = BASE_DIR / os.getenv("GAMEPLAY_DIR", "gameplay")

# Create dirs
for d in [DOWNLOAD_DIR, CLIPS_DIR, SUBTITLES_DIR, GAMEPLAY_DIR, BASE_DIR / "logs"]:
    d.mkdir(exist_ok=True)
