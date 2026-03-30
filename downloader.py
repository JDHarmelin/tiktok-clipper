"""Downloads YouTube videos. Uses pytubefix (primary) with yt-dlp fallback."""
import subprocess
import logging
from pathlib import Path
from config import DOWNLOAD_DIR

logger = logging.getLogger(__name__)


def download_video(url: str) -> dict:
    """
    Download a YouTube video. Tries pytubefix first (bypasses n-challenge),
    falls back to yt-dlp if that fails.
    """
    result = _download_pytubefix(url)
    if result.get("success"):
        return result

    logger.warning(f"pytubefix failed: {result.get('error')}. Trying yt-dlp fallback...")
    return _download_ytdlp(url)


def _download_pytubefix(url: str) -> dict:
    """Download using pytubefix with separate video+audio merge."""
    try:
        from pytubefix import YouTube

        yt = YouTube(url)
        video_id = yt.video_id
        title = yt.title
        duration = yt.length

        # Get best h264 video stream (1080p preferred for fast ffmpeg)
        video_stream = (
            yt.streams
            .filter(file_extension="mp4", type="video", video_codec="avc1.640028")
            .order_by("resolution")
            .desc()
            .first()
        )
        if not video_stream:
            # Fall back to any mp4 video <= 1080p
            video_stream = (
                yt.streams
                .filter(file_extension="mp4", type="video", res="1080p")
                .first()
            )
        if not video_stream:
            video_stream = (
                yt.streams
                .filter(file_extension="mp4", type="video")
                .order_by("resolution")
                .desc()
                .first()
            )
        if not video_stream:
            return {"success": False, "error": "No video streams available"}

        # Get best audio
        audio_stream = (
            yt.streams
            .filter(only_audio=True, file_extension="mp4")
            .order_by("abr")
            .desc()
            .first()
        )

        final_path = DOWNLOAD_DIR / f"{video_id}.mp4"

        if audio_stream and not video_stream.is_progressive:
            # Download separate video and audio, then merge
            vid_path = DOWNLOAD_DIR / f"{video_id}_vid.mp4"
            aud_path = DOWNLOAD_DIR / f"{video_id}_aud.mp4"

            logger.info(f"Downloading video: {video_stream.resolution} {video_stream.video_codec}")
            video_stream.download(output_path=str(DOWNLOAD_DIR), filename=f"{video_id}_vid.mp4")

            logger.info(f"Downloading audio: {audio_stream.abr}")
            audio_stream.download(output_path=str(DOWNLOAD_DIR), filename=f"{video_id}_aud.mp4")

            # Merge with ffmpeg
            logger.info("Merging video + audio...")
            merge_cmd = [
                "ffmpeg", "-y",
                "-i", str(vid_path),
                "-i", str(aud_path),
                "-c:v", "copy",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(final_path),
            ]
            proc = subprocess.run(merge_cmd, capture_output=True, text=True, timeout=120)
            vid_path.unlink(missing_ok=True)
            aud_path.unlink(missing_ok=True)

            if proc.returncode != 0:
                return {"success": False, "error": f"ffmpeg merge failed: {proc.stderr[-300:]}"}
        else:
            # Progressive stream (video+audio combined)
            logger.info(f"Downloading progressive: {video_stream.resolution}")
            video_stream.download(output_path=str(DOWNLOAD_DIR), filename=f"{video_id}.mp4")

        if not final_path.exists():
            return {"success": False, "error": "Download completed but file not found"}

        return {
            "success": True,
            "filepath": str(final_path),
            "title": title,
            "duration": duration,
            "video_id": video_id,
        }

    except Exception as e:
        return {"success": False, "error": f"pytubefix error: {e}"}


def _download_ytdlp(url: str) -> dict:
    """Fallback download using yt-dlp."""
    import yt_dlp

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
        "cookiesfrombrowser": ("chrome",),
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
    except Exception as e:
        return {"success": False, "error": f"yt-dlp error: {e}"}


def fetch_youtube_captions(url: str, video_id: str) -> dict:
    """
    Try to download YouTube's own captions/subtitles.
    Returns caption text and word count if available, or indicates no captions.
    """
    try:
        from pytubefix import YouTube
        yt = YouTube(url)
        captions = yt.captions
        en_caption = captions.get("en") or captions.get("a.en")
        if en_caption:
            text = en_caption.generate_srt_captions()
            word_count = len(text.split())
            return {"has_captions": word_count > 100, "word_count": word_count}
        return {"has_captions": False, "word_count": 0}
    except Exception:
        # Fall back to yt-dlp caption check
        return _fetch_captions_ytdlp(url, video_id)


def _fetch_captions_ytdlp(url: str, video_id: str) -> dict:
    """Fallback caption check using yt-dlp."""
    import yt_dlp
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
            ydl.extract_info(url, download=True)

        possible_paths = [
            DOWNLOAD_DIR / f"{video_id}.en.json3",
            DOWNLOAD_DIR / f"{video_id}.en-orig.json3",
        ]
        possible_paths.extend(DOWNLOAD_DIR.glob(f"{video_id}*.json3"))

        for sub_path in possible_paths:
            sub_path = Path(sub_path)
            if sub_path.exists() and sub_path.stat().st_size > 0:
                try:
                    raw = sub_path.read_text(encoding="utf-8")
                    data = _json.loads(raw)
                    events = data.get("events", [])
                    word_count = 0
                    for event in events:
                        for seg in event.get("segs", []):
                            text = seg.get("utf8", "").strip()
                            if text and text != "\n":
                                word_count += len(text.split())
                    sub_path.unlink()
                    return {"has_captions": word_count > 100, "word_count": word_count}
                except Exception:
                    sub_path.unlink(missing_ok=True)

        return {"has_captions": False, "word_count": 0}
    except Exception as e:
        return {"has_captions": True, "word_count": -1, "note": f"Check failed: {e}"}


def get_video_info(url: str) -> dict:
    """Extract video metadata without downloading."""
    try:
        from pytubefix import YouTube
        yt = YouTube(url)
        return {
            "success": True,
            "title": yt.title,
            "duration": yt.length,
            "channel": yt.author,
            "description": (yt.description or "")[:500],
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to get video info: {e}"}
