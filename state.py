"""SQLite memory for the watcher: which chunks are done, which clips exist and
where they were posted. Lets the watcher restart without redoing work."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
    video_id TEXT NOT NULL,
    seg_start INTEGER NOT NULL,
    streamer TEXT NOT NULL,
    done_at TEXT NOT NULL,
    clip_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (video_id, seg_start)
);
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    streamer TEXT NOT NULL,
    video_id TEXT NOT NULL,
    source_start REAL NOT NULL,
    source_end REAL NOT NULL,
    filepath TEXT NOT NULL,
    caption TEXT NOT NULL,
    title TEXT,
    score INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    clip_id INTEGER NOT NULL,
    account TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (clip_id, account)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path | str = DB_PATH):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- segments ---
    def segment_done(self, video_id: str, seg_start: int) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM segments WHERE video_id=? AND seg_start=?", (video_id, int(seg_start))
        ).fetchone()
        return row is not None

    def mark_segment(self, video_id: str, seg_start: int, streamer: str, clip_count: int):
        self.db.execute(
            "INSERT OR REPLACE INTO segments VALUES (?,?,?,?,?)",
            (video_id, int(seg_start), streamer, _now(), clip_count),
        )
        self.db.commit()

    # --- clips ---
    def overlaps_existing(self, video_id: str, start: float, end: float) -> bool:
        """True if a clip from the same broadcast already covers this time."""
        row = self.db.execute(
            "SELECT 1 FROM clips WHERE video_id=? AND source_start < ? AND source_end > ?",
            (video_id, end, start),
        ).fetchone()
        return row is not None

    def add_clip(self, streamer, video_id, start, end, filepath, caption, title="", score=0) -> int:
        cur = self.db.execute(
            "INSERT INTO clips (streamer, video_id, source_start, source_end, filepath, caption, title, score, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (streamer, video_id, start, end, filepath, caption, title, score, _now()),
        )
        self.db.commit()
        return cur.lastrowid

    def unposted_clips(self, account: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM clips WHERE id NOT IN (SELECT clip_id FROM posts WHERE account=?)"
            " ORDER BY score DESC, id ASC",
            (account,),
        ).fetchall()

    # --- posts ---
    def mark_posted(self, clip_id: int, account: str, verified: bool):
        self.db.execute(
            "INSERT OR REPLACE INTO posts VALUES (?,?,?,?)", (clip_id, account, _now(), int(verified))
        )
        self.db.commit()

    def posts_since(self, account: str, hours: float) -> int:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        row = self.db.execute(
            "SELECT COUNT(*) FROM posts WHERE account=? AND posted_at >= ?", (account, since)
        ).fetchone()
        return row[0]

    def last_post_at(self, account: str) -> datetime | None:
        row = self.db.execute("SELECT MAX(posted_at) FROM posts WHERE account=?", (account,)).fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None
