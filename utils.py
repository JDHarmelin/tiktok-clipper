"""Shared utility functions."""
import os
import glob
from pathlib import Path
from config import DOWNLOAD_DIR, CLIPS_DIR, SUBTITLES_DIR


def cleanup_video(video_id: str):
    """Remove all temp files for a processed video."""
    patterns = [
        DOWNLOAD_DIR / f"{video_id}*",
        CLIPS_DIR / f"{video_id}*",
        SUBTITLES_DIR / f"{video_id}*",
    ]
    for pattern in patterns:
        for f in glob.glob(str(pattern)):
            try:
                os.remove(f)
            except OSError:
                pass


def get_file_size_mb(filepath: str) -> float:
    """Get file size in megabytes."""
    return os.path.getsize(filepath) / (1024 * 1024)


def format_duration(seconds: float) -> str:
    """Format seconds into MM:SS or HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
