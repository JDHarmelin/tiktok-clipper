# TikTok Clipper Agent

Two ways to run it:

- **Stream mode (new):** `watcher.py` watches the streamers in `streamers.json` on Twitch, Kick and YouTube, clips their GTA 6 streams on its own, and (with `--post`) posts to TikTok. No links to send.
- **Link mode (original):** send a YouTube URL to the Telegram bot (`bot.py`).

## Stream mode

```
streamers.json -> watcher.py (every POLL_MINUTES)
   live + GTA 6?  -> record the next 10 min         (sources.record_live)
   else           -> latest VODs in 15 min chunks   (sources.download_section)
                  -> Whisper transcript             (transcriber.py)
                  -> loudness spikes                (signals.py)
                  -> Claude picks moments           (moments.py, structured output)
                  -> 1080x1920 clip, captions, @credit (clipper.extract_stream_clip)
                  -> saved in clipper.db            (state.py)
   --post         -> one clip per account per pass, spaced and capped per day
```

Run it:

```bash
python watcher.py --once --any-game --streamer kaicenat   # test now on any game, clips only
python watcher.py --once                                  # one pass over everyone, GTA 6 only
python watcher.py --post                                  # run forever and post to TikTok
python watcher.py --url <vod url> --streamer kaicenat --start 3600   # clip one 15 min chunk
```

Clips land in `clips/`; nothing is posted unless you pass `--post`.

Edit `streamers.json` to add or remove streamers. Set `facecam` to `[x, y, w, h]` (fractions of the frame) for a streamer's webcam to get the facecam-over-gameplay layout; leave it `null` for the full frame over a blurred background. Check each handle before the first run.

Every clip burns in the streamer's credit tag and puts it in the caption. Clip programs usually ban view bots and reposting other clippers' clips, and want the streamer tagged.

Tests: `python -m pytest test_stream.py -q` (no API key or network needed).

## Link mode (original)

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

- Anthropic API: priced per model in `config.MODEL_PRICES` (default Claude Opus 5.5)
- Local Whisper: free (runs on CPU/GPU)
- Total infrastructure: ~$0-5/month running locally
