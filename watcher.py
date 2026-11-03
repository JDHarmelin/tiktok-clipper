"""Autonomous GTA 6 stream clipper. Replaces sending links through Telegram.

Each pass, for every enabled streamer in streamers.json:
  1. Live and playing GTA 6 -> record the next few minutes and clip them.
  2. Otherwise -> look at their latest broadcasts and clip GTA 6 ones in
     15-minute chunks, skipping chunks already done.
Then, with --post, upload queued clips to every TikTok account, spaced out and
capped per day.

Usage:
  python watcher.py --once                 # one pass, clips only (nothing posted)
  python watcher.py                        # keep running, a pass every POLL_MINUTES
  python watcher.py --post                 # also post clips to TikTok
  python watcher.py --streamer kaicenat    # only this streamer
  python watcher.py --any-game             # don't require GTA 6 (for testing on GTA 5 RP now)
  python watcher.py --url <vod url> --streamer kaicenat --start 3600   # clip one chunk of a given VOD
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

from config import (
    BASE_DIR,
    MAX_POSTS_PER_ACCOUNT_PER_DAY,
    MIN_MINUTES_BETWEEN_POSTS,
    POLL_MINUTES,
    SEGMENT_SECONDS,
    SEGMENTS_PER_RUN,
)
from sources import StreamInfo, check_live, fill_details, list_recent_vods, load_streamers
from state import State
from stream_pipeline import process_chunk

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler(BASE_DIR / "logs" / "watcher.log"), logging.StreamHandler()],
)
log = logging.getLogger("watcher")


def notify(msg: str):
    log.info(msg)


def vod_chunks(duration: float, seg: int = SEGMENT_SECONDS) -> list[tuple[int, int]]:
    """Split a broadcast into [start, end) chunks, dropping a tiny tail."""
    chunks, t = [], 0
    while t < duration:
        end = int(min(t + seg, duration))
        if end - t >= 60:
            chunks.append((t, end))
        t += seg
    return chunks


def clip_streamer(s, state: State, any_game: bool) -> int:
    made = 0
    live = check_live(s)
    if live:
        if any_game or live.is_gta6:
            made += len(process_chunk(live, state, int(time.time()), 0, notify))
        else:
            notify(f"[{s.name}] live but not GTA 6 ('{live.title}'), skipping")
        return made

    budget = SEGMENTS_PER_RUN
    for vod in list_recent_vods(s, limit=3):
        vod = fill_details(vod)
        if not (any_game or vod.is_gta6):
            continue
        for start, end in vod_chunks(vod.duration):
            if budget <= 0:
                return made
            if state.segment_done(vod.video_id, start):
                continue
            made += len(process_chunk(vod, state, start, end, notify))
            budget -= 1
    return made


def post_queue(state: State):
    from tiktok_poster import list_accounts, upload_to_tiktok

    for acct in list_accounts():
        if state.posts_since(acct, 24) >= MAX_POSTS_PER_ACCOUNT_PER_DAY:
            notify(f"[{acct}] daily post cap reached")
            continue
        last = state.last_post_at(acct)
        if last and datetime.now(timezone.utc) - last < timedelta(minutes=MIN_MINUTES_BETWEEN_POSTS):
            continue
        queue = state.unposted_clips(acct)
        if not queue:
            continue
        clip = queue[0]  # one post per account per pass keeps posting spread out
        res = upload_to_tiktok(video_path=clip["filepath"], caption=clip["caption"], account_name=acct)
        if res.get("success"):
            state.mark_posted(clip["id"], acct, bool(res.get("verified")))
            notify(f"[{acct}] posted {clip['filepath']}")
        else:
            notify(f"[{acct}] post failed: {res.get('error')}")


def one_pass(args, state: State):
    streamers = [s for s in load_streamers() if s.enabled]
    if args.streamer:
        streamers = [s for s in streamers if s.handle.lower() == args.streamer.lower()]
    total = 0
    for s in streamers:
        try:
            total += clip_streamer(s, state, args.any_game)
        except Exception as e:
            log.exception(f"[{s.name}] pass failed: {e}")
    notify(f"pass done: {total} new clip(s)")
    if args.post:
        post_queue(state)


def main():
    p = argparse.ArgumentParser(description="GTA 6 stream clipper")
    p.add_argument("--once", action="store_true", help="run one pass and exit")
    p.add_argument("--post", action="store_true", help="upload clips to TikTok (off by default)")
    p.add_argument("--streamer", help="only this handle from streamers.json")
    p.add_argument("--any-game", action="store_true", help="clip any game, not just GTA 6")
    p.add_argument("--url", help="clip one chunk of this VOD URL (needs --streamer)")
    p.add_argument("--start", type=int, default=0, help="with --url: chunk start in seconds")
    args = p.parse_args()
    state = State()

    if args.url:
        match = [s for s in load_streamers() if s.handle.lower() == (args.streamer or "").lower()]
        if not match:
            raise SystemExit("--url needs --streamer <handle from streamers.json>")
        vod = fill_details(StreamInfo(match[0], args.url, args.url.rstrip("/").split("/")[-1], "", False))
        end = int(min(args.start + SEGMENT_SECONDS, vod.duration or args.start + SEGMENT_SECONDS))
        process_chunk(vod, state, args.start, end, notify, keep_source=True)
        return

    while True:
        one_pass(args, state)
        if args.once:
            break
        time.sleep(POLL_MINUTES * 60)


if __name__ == "__main__":
    main()
