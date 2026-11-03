"""Hype signals for long streams.

Streams are mostly gameplay with bursts of yelling, laughing or chat going off.
Loud moments are a cheap, reliable hint for where the clips are, so we measure
per-second loudness with ffmpeg and flag the spikes. Claude gets these as hints
alongside the transcript.
"""
from __future__ import annotations

import re
import statistics
import subprocess

_PTS = re.compile(r"pts_time:([\d.]+)")
_MOMENTARY = re.compile(r"lavfi\.r128\.M=(-?[\d.]+|-inf)")


def loudness_series(path: str) -> list[float]:
    """Momentary loudness (LUFS) for each second of the file's audio."""
    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", path, "-vn",
        "-af", "ebur128=metadata=1,ametadata=print:key=lavfi.r128.M:file=-",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    per_second: dict[int, float] = {}
    t = None
    for line in proc.stdout.splitlines():
        m = _PTS.search(line)
        if m:
            t = int(float(m.group(1)))
            continue
        m = _MOMENTARY.search(line)
        if m and t is not None:
            val = -70.0 if m.group(1) == "-inf" else float(m.group(1))
            per_second[t] = max(per_second.get(t, -70.0), val)
    if not per_second:
        return []
    return [per_second.get(i, -70.0) for i in range(max(per_second) + 1)]


def find_spikes(series: list[float], z: float = 2.0, min_gap: int = 20, top_k: int = 15) -> list[dict]:
    """Seconds where loudness jumps well above the stream's normal level.

    Returns [{"t": second, "level": lufs, "score": z_score}], strongest first,
    with spikes closer than min_gap seconds merged into the loudest one.
    """
    if len(series) < 10:
        return []
    # Ignore silence when measuring the baseline so quiet pauses don't skew it
    voiced = [v for v in series if v > -60] or series
    mean = statistics.fmean(voiced)
    sd = statistics.pstdev(voiced) or 1.0
    candidates = [
        {"t": i, "level": round(v, 1), "score": round((v - mean) / sd, 2)}
        for i, v in enumerate(series)
        if (v - mean) / sd >= z
    ]
    candidates.sort(key=lambda c: c["score"], reverse=True)
    kept: list[dict] = []
    for c in candidates:
        if all(abs(c["t"] - k["t"]) >= min_gap for k in kept):
            kept.append(c)
        if len(kept) >= top_k:
            break
    return kept


def audio_spikes(path: str, **kw) -> list[dict]:
    try:
        return find_spikes(loudness_series(path), **kw)
    except Exception:
        return []
