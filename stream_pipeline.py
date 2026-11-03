"""One chunk of a stream in, finished clips out.

download/record chunk -> Whisper transcript -> loudness spikes -> Claude picks
moments -> ffmpeg cuts vertical clips with captions and credit -> saved to the
database for the uploader.
"""
from __future__ import annotations

import logging
from pathlib import Path

from config import CLIPS_PER_SEGMENT, LIVE_RECORD_SECONDS
from moments import build_caption, pick_moments
from signals import audio_spikes
from sources import StreamInfo, download_section, record_live
from state import State

logger = logging.getLogger(__name__)


def _transcribe(path: str) -> tuple[str, list]:
    from transcriber import transcribe_video  # loads Whisper only when needed

    result = transcribe_video(path)
    if not result.get("success"):
        logger.warning(f"Transcription failed: {result.get('error')}")
        return "", []
    return result["formatted_transcript"], result["words"]


def process_chunk(
    stream: StreamInfo,
    state: State,
    seg_start: float,
    seg_end: float,
    notify=print,
    keep_source: bool = False,
) -> list[int]:
    """Clip one chunk. seg_start/seg_end are seconds into the VOD (ignored when live)."""
    s = stream.streamer
    tag = f"{s.slug}_{stream.video_id}_{int(seg_start)}"
    if stream.is_live:
        notify(f"[{s.name}] recording {LIVE_RECORD_SECONDS // 60} min of the live stream")
        got = record_live(stream.url, LIVE_RECORD_SECONDS, tag)
    else:
        notify(f"[{s.name}] downloading {int(seg_start)}s-{int(seg_end)}s of '{stream.title}'")
        got = download_section(stream.url, seg_start, seg_end, tag)
    if not got.get("success"):
        notify(f"[{s.name}] download failed: {got.get('error')}")
        return []
    path = got["filepath"]
    chunk_len = float(got["end"] - got["start"])

    transcript, words = _transcribe(path)
    spikes = audio_spikes(path)
    moments, usage = pick_moments(s.name, transcript, spikes, chunk_len, CLIPS_PER_SEGMENT, stream.title)
    notify(f"[{s.name}] {len(moments)} moment(s) picked "
           f"({usage['input_tokens']} in / {usage['output_tokens']} out tokens)")

    from clipper import extract_stream_clip

    clip_ids = []
    for i, m in enumerate(moments):
        abs_start, abs_end = seg_start + m.start, seg_start + m.end
        if not stream.is_live and state.overlaps_existing(stream.video_id, abs_start, abs_end):
            continue
        res = extract_stream_clip(
            path, m.start, m.end, f"{tag}_{i:02d}",
            words=words, facecam=s.facecam, credit=s.credit, platform=s.platform, socials=s.socials,
        )
        if not res.get("success"):
            notify(f"[{s.name}] clip failed: {res.get('error')}")
            continue
        caption = build_caption(m, s.credit)
        clip_ids.append(state.add_clip(
            s.slug, stream.video_id, abs_start, abs_end, res["filepath"], caption, m.title, m.score))
        notify(f"[{s.name}] clip ready: {res['filename']} | {caption}")

    state.mark_segment(stream.video_id, int(seg_start), s.slug, len(clip_ids))
    if not keep_source:
        Path(path).unlink(missing_ok=True)
    return clip_ids
