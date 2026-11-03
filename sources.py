"""Stream sources for Twitch, Kick and YouTube, all through yt-dlp.

- load_streamers(): read streamers.json
- check_live(): is the streamer live, and is the stream GTA 6?
- list_recent_vods(): the streamer's latest past broadcasts
- download_section(): download only [start, end) of a VOD, not the whole thing
- record_live(): record the next N seconds of a live stream
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from config import BASE_DIR, DOWNLOAD_DIR, GAME_KEYWORDS

logger = logging.getLogger(__name__)

STREAMERS_FILE = BASE_DIR / "streamers.json"
PLATFORMS = ("twitch", "kick", "youtube")


@dataclass
class Streamer:
    name: str
    platform: str
    handle: str
    credit: str
    facecam: list[float] | None = None
    enabled: bool = True
    socials: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return f"{self.platform}_{self.handle.lower()}"


@dataclass
class StreamInfo:
    streamer: Streamer
    url: str
    video_id: str
    title: str
    is_live: bool
    duration: float = 0.0
    categories: list[str] = field(default_factory=list)

    @property
    def is_gta6(self) -> bool:
        return matches_game(self.title, self.categories)


def load_streamers(path: Path = STREAMERS_FILE) -> list[Streamer]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for row in data.get("streamers", []):
        s = Streamer(
            name=row["name"],
            platform=row["platform"].lower(),
            handle=row["handle"],
            credit=row.get("credit") or f"@{row['handle'].lower()}",
            facecam=row.get("facecam"),
            enabled=row.get("enabled", True),
            socials=[x.lower() for x in row.get("socials", [])],
        )
        if s.platform not in PLATFORMS:
            raise ValueError(f"{s.name}: unknown platform '{s.platform}'")
        out.append(s)
    return out


def live_url(s: Streamer) -> str:
    if s.platform == "twitch":
        return f"https://www.twitch.tv/{s.handle}"
    if s.platform == "kick":
        return f"https://kick.com/{s.handle}"
    return f"https://www.youtube.com/@{s.handle}/live"


def vods_url(s: Streamer) -> str:
    if s.platform == "twitch":
        return f"https://www.twitch.tv/{s.handle}/videos?filter=archives&sort=time"
    if s.platform == "kick":
        return f"https://kick.com/{s.handle}/videos"
    return f"https://www.youtube.com/@{s.handle}/streams"


def matches_game(title: str, categories: list[str] | None = None) -> bool:
    """True when the stream title or category names GTA 6."""
    haystack = " ".join([title or ""] + list(categories or [])).lower()
    return any(k.lower() in haystack for k in GAME_KEYWORDS)


def _ydl(extra: dict | None = None):
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "socket_timeout": 30, "retries": 3}
    if extra:
        opts.update(extra)
    return yt_dlp.YoutubeDL(opts)


def _categories(info: dict) -> list[str]:
    cats = list(info.get("categories") or [])
    for key in ("category", "game"):
        if info.get(key):
            cats.append(str(info[key]))
    return cats


def check_live(s: Streamer) -> StreamInfo | None:
    """Return StreamInfo if the streamer is live right now, else None."""
    url = live_url(s)
    try:
        with _ydl() as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # yt-dlp raises when the channel is offline
        logger.debug(f"{s.name} not live ({e})")
        return None
    if not info or not info.get("is_live", info.get("live_status") == "is_live"):
        return None
    return StreamInfo(
        streamer=s,
        url=info.get("webpage_url") or url,
        video_id=str(info.get("id")),
        title=info.get("title") or "",
        is_live=True,
        categories=_categories(info),
    )


def list_recent_vods(s: Streamer, limit: int = 3) -> list[StreamInfo]:
    """Latest past broadcasts, newest first. Durations may be 0 until fetched."""
    try:
        with _ydl({"extract_flat": "in_playlist", "playlistend": limit}) as ydl:
            info = ydl.extract_info(vods_url(s), download=False)
    except Exception as e:
        logger.warning(f"{s.name}: could not list VODs ({e})")
        return []
    vods = []
    for entry in (info or {}).get("entries", [])[:limit]:
        if not entry:
            continue
        url = entry.get("url") or entry.get("webpage_url")
        if not url:
            continue
        if url.startswith("/"):
            url = {"twitch": "https://www.twitch.tv", "kick": "https://kick.com"}.get(s.platform, "") + url
        vods.append(StreamInfo(
            streamer=s,
            url=url,
            video_id=str(entry.get("id")),
            title=entry.get("title") or "",
            is_live=entry.get("live_status") == "is_live",
            duration=float(entry.get("duration") or 0),
            categories=_categories(entry),
        ))
    return [v for v in vods if not v.is_live]


def fill_details(v: StreamInfo) -> StreamInfo:
    """Fetch full metadata (duration, categories) for a VOD found by list_recent_vods."""
    try:
        with _ydl() as ydl:
            info = ydl.extract_info(v.url, download=False)
        v.duration = float(info.get("duration") or v.duration or 0)
        v.title = info.get("title") or v.title
        v.categories = _categories(info) or v.categories
    except Exception as e:
        logger.warning(f"Could not read details for {v.url}: {e}")
    return v


def download_section(url: str, start: float, end: float, out_name: str) -> dict:
    """Download only [start, end) seconds of a VOD to downloads/<out_name>.mp4."""
    from yt_dlp.utils import download_range_func

    out_path = DOWNLOAD_DIR / f"{out_name}.mp4"
    opts = {
        "outtmpl": str(DOWNLOAD_DIR / f"{out_name}.%(ext)s"),
        "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "merge_output_format": "mp4",
        "download_ranges": download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": False,
        "fragment_retries": 5,
    }
    try:
        with _ydl(opts) as ydl:
            ydl.extract_info(url, download=True)
    except Exception as e:
        return {"success": False, "error": f"yt-dlp section download failed: {e}"}
    if not out_path.exists():
        found = sorted(DOWNLOAD_DIR.glob(f"{out_name}.*"))
        if not found:
            return {"success": False, "error": "section download finished but no file was written"}
        out_path = found[0]
    return {"success": True, "filepath": str(out_path), "start": start, "end": end}


def record_live(url: str, seconds: int, out_name: str) -> dict:
    """Record the next `seconds` of a live stream to downloads/<out_name>.mp4."""
    try:
        with _ydl({"format": "best[height<=1080]/best"}) as ydl:
            info = ydl.extract_info(url, download=False)
        stream_url = info["url"]
        headers = info.get("http_headers") or {}
    except Exception as e:
        return {"success": False, "error": f"could not resolve live stream: {e}"}

    out_path = DOWNLOAD_DIR / f"{out_name}.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if headers:
        cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
    cmd += ["-i", stream_url, "-t", str(seconds), "-c", "copy", "-movflags", "+faststart", str(out_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 120)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "live recording timed out"}
    if proc.returncode != 0 or not out_path.exists():
        return {"success": False, "error": f"ffmpeg live record failed: {proc.stderr[-300:]}"}
    return {"success": True, "filepath": str(out_path), "start": 0, "end": seconds}
