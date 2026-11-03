"""Tests for stream mode. No network, no API key, no Whisper needed.

Run with: python -m pytest test_stream.py -q
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("DB_PATH", "test_clipper.db")

import pytest

from moments import Moment, build_caption, clean_moments
from signals import find_spikes, loudness_series
from sources import Streamer, live_url, load_streamers, matches_game, vods_url
from state import State
from watcher import vod_chunks


def _m(start, end, score=5, caption="he really did that", tags=("gta",)):
    return Moment(start=start, end=end, title="t", hook="h", score=score,
                  caption=caption, hashtags=list(tags), reason="r")


# ---- sources ----

def test_streamers_file_loads():
    streamers = load_streamers()
    assert any(s.handle == "kaicenat" and s.platform == "twitch" for s in streamers)
    assert all(s.credit.startswith("@") for s in streamers)


def test_urls():
    tw = Streamer("A", "twitch", "kaicenat", "@kaicenat")
    kk = Streamer("B", "kick", "adinross", "@adinross")
    yt = Streamer("C", "youtube", "IShowSpeed", "@ishowspeed")
    assert live_url(tw) == "https://www.twitch.tv/kaicenat"
    assert live_url(kk) == "https://kick.com/adinross"
    assert live_url(yt) == "https://www.youtube.com/@IShowSpeed/live"
    assert "filter=archives" in vods_url(tw)
    assert vods_url(yt).endswith("/streams")


def test_game_filter():
    assert matches_game("FIRST DAY IN GTA 6 !!!", [])
    assert matches_game("chilling", ["Grand Theft Auto VI"])
    assert not matches_game("GTA RP NoPixel", ["Grand Theft Auto V"])


def test_bad_platform(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"streamers": [{"name": "x", "platform": "myspace", "handle": "x"}]}))
    with pytest.raises(ValueError):
        load_streamers(f)


# ---- signals ----

def test_spikes_found_and_merged():
    series = [-30.0] * 300
    series[100] = -8.0
    series[105] = -9.0   # within min_gap of 100, merged away
    series[200] = -10.0
    spikes = find_spikes(series, z=2.0, min_gap=20)
    assert [s["t"] for s in spikes] == [100, 200]


def test_no_spikes_in_flat_audio():
    assert find_spikes([-25.0] * 120) == []


# ---- moments ----

def test_clean_moments_limits_and_overlap():
    ms = [
        _m(10, 50, score=9),
        _m(40, 80, score=8),     # overlaps the 9
        _m(100, 105, score=7),   # too short
        _m(200, 400, score=6),   # too long, trimmed to MAX
        _m(890, 1000, score=5),  # runs past chunk end, clamped
    ]
    out = clean_moments(ms, chunk_len=900, max_clips=5)
    assert [(m.start, m.end) for m in out] == [(10, 50), (200, 290)]


def test_caption_always_credits_streamer():
    cap = build_caption(_m(0, 30, caption="x" * 300, tags=("#GTA6", "fyp", "kai cenat")), "@kaicenat")
    assert "@kaicenat" in cap
    assert len(cap) <= 150
    assert cap.count("#fyp") == 1 and cap.count("#gta6") == 1
    assert "#kaicenat" in cap


# ---- state ----

def test_state_dedupes(tmp_path):
    st = State(tmp_path / "db.sqlite")
    assert not st.segment_done("v1", 0)
    st.mark_segment("v1", 0, "twitch_kaicenat", 2)
    assert st.segment_done("v1", 0)
    cid = st.add_clip("twitch_kaicenat", "v1", 100, 140, "/x.mp4", "cap", "t", 9)
    assert st.overlaps_existing("v1", 120, 160)
    assert not st.overlaps_existing("v1", 141, 170)
    assert [r["id"] for r in st.unposted_clips("default")] == [cid]
    st.mark_posted(cid, "default", True)
    assert st.unposted_clips("default") == []
    assert st.posts_since("default", 24) == 1


def test_vod_chunks():
    assert vod_chunks(2000, 900) == [(0, 900), (900, 1800), (1800, 2000)]
    assert vod_chunks(1830, 900) == [(0, 900), (900, 1800)]  # 30s tail dropped


# ---- rendering (needs ffmpeg) ----

def _fake_stream(path: Path, seconds=12):
    """1920x1080 'gameplay' with a facecam box top-left and a loud burst at 6s."""
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
        "-filter_complex",
        "[0:v]drawbox=x=40:y=40:w=480:h=270:color=orange@1:t=fill[v];"
        "[1:a]volume='if(between(t,6,7),1.0,0.05)':eval=frame[a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", str(path),
    ], check=True)


@pytest.mark.parametrize("facecam", [None, [0.02, 0.04, 0.25, 0.25]])
def test_render_stream_clip(tmp_path, facecam):
    from clipper import extract_stream_clip

    src = tmp_path / "src.mp4"
    _fake_stream(src)
    words = [{"word": w, "start": 1 + i * 0.4, "end": 1.3 + i * 0.4}
             for i, w in enumerate("NO WAY HE JUST CRASHED THE COP CAR".split())]
    res = extract_stream_clip(str(src), 0.5, 9.5, f"test_{'cam' if facecam else 'fit'}",
                              words=words, facecam=facecam, credit="@kaicenat")
    assert res["success"], res
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", res["filepath"]],
        capture_output=True, text=True,
    )
    assert probe.stdout.strip() == "1080,1920"
    Path(res["filepath"]).unlink()


def test_loudness_spike_on_real_audio(tmp_path):
    src = tmp_path / "src.mp4"
    _fake_stream(src)
    spikes = find_spikes(loudness_series(str(src)), z=1.5, min_gap=3)
    assert spikes and 5 <= spikes[0]["t"] <= 8
