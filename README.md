# TikTok Clipper Agent

Automated YouTube-to-TikTok pipeline. Send a YouTube URL via Telegram, and the agent downloads the video, transcribes it, uses Claude AI to identify viral moments, cuts 9:16 clips with burned-in captions, and posts them to TikTok.

## Architecture

```
Telegram Bot -> Claude Orchestrator (tool_use API)
                    |-> yt-dlp (download)
                    |-> faster-whisper (transcribe)
                    |-> Claude AI (viral moment detection)
                    |-> ffmpeg (clip extraction + captions)
                    |-> tiktok-uploader (post to TikTok)
```

## Setup

1. **Install dependencies**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   python -m playwright install
   python -m playwright install-deps
   ```

2. **Install ffmpeg** (if not already installed)
   ```bash
   # macOS
   brew install ffmpeg
   ```

3. **Configure credentials**
   ```bash
   cp .env.example .env
   # Edit .env with your actual API keys
   ```

4. **Export TikTok cookies**
   - Log into tiktok.com in Chrome
   - Install "Get cookies.txt LOCALLY" extension
   - Export cookies on tiktok.com and save as `cookies.txt` in project root

5. **Run the bot**
   ```bash
   python bot.py
   ```

6. **Send a YouTube URL** to your Telegram bot

## Multiple TikTok Accounts

Place additional cookie files in the project root (e.g., `cookies_account2.txt`) and register them in `tiktok_poster.py`:

```python
from tiktok_poster import register_account
register_account("account2", "./cookies_account2.txt")
```

## Cost

- Anthropic API: ~$0.01-0.05 per video (Claude Sonnet)
- Local Whisper: free (runs on CPU/GPU)
- Total infrastructure: ~$0-5/month running locally
