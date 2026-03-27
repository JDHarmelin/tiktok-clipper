"""Downloads YouTube videos using yt-dlp as a Python library."""
import yt_dlp
from pathlib import Path
from config import DOWNLOAD_DIR


def download_video(url: str) -> dict:
    """
    Download a YouTube video. Returns dict with filepath, title, duration.
    Prefers h264/mp4 at 1080p max for fast ffmpeg processing.
    """
    output_template = str(DOWNLOAD_DIR / "%(id)s.%(ext)s")

    ydl_opts = {
        "outtmpl": output_template,
        "format": (
            "bestvideo[vcodec^=avc1][height<=1080]+bestaudio[acodec^=mp4a]/"
            "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/"
            "best[ext=mp4][height<=1080]/best"
        ),
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "geo_bypass": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = Path(info["requested_downloads"][0]["filepath"])
            return {
                "success": True,
                "filepath": str(filepath),
                "title": info.get("title", "Unknown"),
                "duration": info.get("duration", 0),
                "video_id": info.get("id", "unknown"),
            }
    except yt_dlp.utils.DownloadError as e:
        return {"success": False, "error": f"Download failed: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {e}"}


def fetch_youtube_captions(url: str, video_id: str) -> dict:
    """
    Try to download YouTube's own captions/subtitles.
    Returns caption text and word count if available, or indicates no captions.
    This is instant (no Whisper needed) and lets us skip transcription for
    videos without speech.
    """
    from config import DOWNLOAD_DIR
    import json as _json

    sub_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writeautomaticsub": True,
        "writesubtitles": True,
        "subtitleslangs": ["en"],
        "subtitlesformat": "json3",
        "outtmpl": str(DOWNLOAD_DIR / "%(id)s"),
        "socket_timeout": 15,
    }

    try:
        with yt_dlp.YoutubeDL(sub_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Check for downloaded subtitle files
        possible_paths = [
            DOWNLOAD_DIR / f"{video_id}.en.json3",
            DOWNLOAD_DIR / f"{video_id}.en-orig.json3",
        ]
        # Also check for any .json3 file matching the video ID
        possible_paths.extend(DOWNLOAD_DIR.glob(f"{video_id}*.json3"))

        for sub_path in possible_paths:
            sub_path = Path(sub_path)
            if sub_path.exists() and sub_path.stat().st_size > 0:
                try:
                    raw = sub_path.read_text(encoding="utf-8")
                    data = _json.loads(raw)
                    events = data.get("events", [])
                    # Count words from caption events
                    word_count = 0
                    for event in events:
                        segs = event.get("segs", [])
                        for seg in segs:
                            text = seg.get("utf8", "").strip()
                            if text and text != "\n":
                                word_count += len(text.split())
                    # Clean up subtitle file
                    sub_path.unlink()
                    # Videos with real speech typically have 500+ words
                    # Under 100 words is usually just noise/music misdetected
                    return {
                        "has_captions": word_count > 100,
                        "word_count": word_count,
                    }
                except Exception:
                    sub_path.unlink(missing_ok=True)

        return {"has_captions": False, "word_count": 0}

    except Exception as e:
        # If caption check fails, assume captions might exist (don't skip transcription)
        return {"has_captions": True, "word_count": -1, "note": f"Check failed: {e}"}


def get_video_info(url: str) -> dict:
    """Extract video metadata without downloading."""
    try:
        with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "success": True,
                "title": info.get("title"),
                "duration": info.get("duration"),
                "channel": info.get("channel"),
                "description": info.get("description", "")[:500],
            }
    except yt_dlp.utils.DownloadError as e:
        return {"success": False, "error": f"Failed to get video info: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {e}"}
