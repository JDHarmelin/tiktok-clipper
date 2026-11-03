"""Extracts clips from video, reformats to 9:16 split-screen with gameplay, burns in captions."""
import random
import subprocess
from pathlib import Path
from config import OUTPUT_WIDTH, OUTPUT_HEIGHT, CLIPS_DIR, SUBTITLES_DIR, GAMEPLAY_DIR, BASE_DIR, STREAM_LAYOUT, OUR_HANDLE


def _get_random_gameplay() -> Path | None:
    """Pick a random gameplay video from the gameplay directory."""
    videos = list(GAMEPLAY_DIR.glob("*.mp4"))
    if not videos:
        return None
    return random.choice(videos)


def extract_clip(
    input_video: str,
    start: float,
    end: float,
    clip_index: int,
    video_id: str,
    words: list = None,
) -> dict:
    """
    Extract a clip with split-screen layout:
      - Top half: main YouTube content
      - Bottom half: GTA gameplay (random start point)
      - Captions in the middle between the two halves
    Falls back to full-frame center-crop if no gameplay videos available.
    """
    # Validate timestamps
    if start < 0:
        return {"success": False, "error": f"Invalid start time: {start} (negative)"}
    if end <= start:
        return {"success": False, "error": f"Invalid timestamps: end ({end}) must be greater than start ({start})"}

    # Validate input video exists
    if not Path(input_video).exists():
        return {"success": False, "error": f"Input video not found: {input_video}"}

    duration = end - start
    output_filename = f"{video_id}_clip_{clip_index:02d}.mp4"
    output_path = CLIPS_DIR / output_filename

    gameplay_path = _get_random_gameplay()

    # Generate captions
    ass_path = None
    if words:
        ass_path = _generate_ass_subtitles(words, start, end, clip_index, video_id,
                                           split_screen=gameplay_path is not None)

    # Try with subtitles first, fall back to no subtitles
    for attempt_subs in ([True, False] if ass_path else [False]):
        if gameplay_path:
            cmd = _build_split_screen_cmd(
                input_video, str(gameplay_path), start, duration,
                output_path, ass_path if attempt_subs else None,
            )
        else:
            cmd = _build_fullframe_cmd(
                input_video, start, duration,
                output_path, ass_path if attempt_subs else None,
            )

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
                cwd=str(BASE_DIR),
            )
            if result.returncode == 0:
                return {
                    "success": True,
                    "filepath": str(output_path),
                    "filename": output_filename,
                    "duration": round(duration, 1),
                    "has_captions": attempt_subs,
                    "split_screen": gameplay_path is not None,
                }
            if attempt_subs:
                continue
            return {"success": False, "error": result.stderr[-500:]}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "ffmpeg timed out after 5 minutes"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return {"success": False, "error": "All ffmpeg attempts failed"}


def _build_split_screen_cmd(
    input_video: str, gameplay_video: str,
    start: float, duration: float,
    output_path: Path, ass_path: Path | None,
) -> list:
    """
    Build ffmpeg command for split-screen layout (1080x1920):
      - Top half (1080x960): main content, center-cropped to 16:9 then scaled
      - Bottom half (1080x960): gameplay, random start, center-cropped then scaled
      - Captions overlay in the middle via ASS subtitles
    """
    # Random start point in gameplay (avoid first/last 30s)
    gameplay_start = random.randint(30, 600)

    # Filter: crop main to 16:9, scale to top half; crop gameplay, scale to bottom half; stack
    filter_parts = [
        # Input 0: main video — crop to 16:9 center, scale to 1080x960
        "[0:v]crop=iw:iw*9/16,scale=1080:960,setsar=1[top]",
        # Input 1: gameplay — crop to 16:9 center, scale to 1080x960
        "[1:v]crop=iw:iw*9/16,scale=1080:960,setsar=1[bottom]",
        # Stack vertically
        "[top][bottom]vstack=inputs=2[stacked]",
    ]

    # Add subtitles overlay if available
    if ass_path:
        escaped = str(ass_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        filter_parts.append(f"[stacked]ass={escaped}[out]")
        final_label = "[out]"
    else:
        final_label = "[stacked]"

    vf_string = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", input_video,
        "-ss", str(gameplay_start),
        "-i", gameplay_video,
        "-t", str(duration),
        "-filter_complex", vf_string,
        "-map", final_label,
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-threads", "0",
        "-shortest",
        str(output_path),
    ]
    return cmd


def _build_fullframe_cmd(
    input_video: str, start: float, duration: float,
    output_path: Path, ass_path: Path | None,
) -> list:
    """Fallback: full-frame center-crop to 9:16 (no gameplay)."""
    vf_filters = [
        "crop=ih*9/16:ih",
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}",
        "setsar=1",
    ]

    if ass_path:
        escaped = str(ass_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        vf_filters.append(f"ass={escaped}")

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", input_video,
        "-t", str(duration),
        "-vf", ",".join(vf_filters),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-threads", "0",
        str(output_path),
    ]
    return cmd


def _generate_ass_subtitles(
    all_words: list,
    clip_start: float,
    clip_end: float,
    clip_index: int,
    video_id: str,
    split_screen: bool = False,
) -> Path | None:
    """
    Generate ASS subtitle file with captions.
    Split-screen mode: captions centered in the middle (between top and bottom halves).
    Full-frame mode: captions in lower third.
    Style: large bold white text with thick black outline.
    """
    clip_words = [
        w for w in all_words
        if w["start"] >= clip_start - 0.1 and w["end"] <= clip_end + 0.1
    ]

    if not clip_words:
        return None

    ass_path = SUBTITLES_DIR / f"{video_id}_clip_{clip_index:02d}.ass"

    # Position: for split-screen, center vertically (around y=960 in 1920px)
    # MarginV from bottom: 1920 - 960 = 960, so ~880 to sit right at the seam
    # For full-frame: lower third, MarginV ~180
    if split_screen:
        margin_v = 880
    else:
        margin_v = 180

    header = f"""[Script Info]
Title: TikTok Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,82,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,0,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    phrases = _group_words_into_phrases(clip_words, words_per_phrase=4)

    for phrase in phrases:
        phrase_start = phrase[0]["start"] - clip_start
        phrase_end = phrase[-1]["end"] - clip_start

        if phrase_start < 0:
            phrase_start = 0

        start_ts = _format_ass_time(phrase_start)
        end_ts = _format_ass_time(phrase_end)
        text = " ".join(w["word"].strip() for w in phrase)

        events.append(
            f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{{\\an2}}{text}"
        )

    ass_content = header + "\n".join(events) + "\n"
    # Encode with surrogatepass to handle stray surrogates, then decode
    # back to a clean UTF-8 string (replacing any unencodable chars).
    safe_content = ass_content.encode("utf-8", errors="replace").decode("utf-8")
    ass_path.write_text(safe_content, encoding="utf-8")
    return ass_path


def _group_words_into_phrases(words: list, words_per_phrase: int = 4) -> list:
    """Group words into display phrases for subtitle readability."""
    phrases = []
    current_phrase = []
    for word in words:
        current_phrase.append(word)
        if len(current_phrase) >= words_per_phrase:
            phrases.append(current_phrase)
            current_phrase = []
    if current_phrase:
        phrases.append(current_phrase)
    return phrases


def _format_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format (H:MM:SS.cc)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


# ============================================================
# Stream clips (watcher.py): facecam over gameplay, or blurred fit
# ============================================================

FACECAM_H = 640  # top band height in the facecam layout; gameplay gets the rest
# "zoom" layout: a sharp, zoomed-in centre crop of the stream on a blurred copy
# of itself, with the streamer's name in the band above it
ZOOM_TOP = 527
ZOOM_H = 990


def extract_stream_clip(
    input_video: str,
    start: float,
    end: float,
    out_name: str,
    words: list | None = None,
    facecam: list[float] | None = None,
    credit: str = "",
    platform: str = "",
    layout: str | None = None,
    socials: list[str] | None = None,
    our_handle: str | None = None,
) -> dict:
    """Cut a 1080x1920 clip from stream footage.

    Layouts:
    - "zoom" (default): zoomed centre crop of the stream in the middle, blurred
      copy above and below, the streamer's socials (icons + handle) in the top
      band and your own handle (OUR_HANDLE) in the bottom band if set.
    - "facecam": webcam on top, gameplay below. Used when facecam is set
      ([x, y, w, h] as fractions of the frame).
    - "fit": the whole frame, small, over a blurred copy. Nothing cropped.
    Captions and the streamer credit are burned in on every layout.
    """
    if start < 0 or end <= start:
        return {"success": False, "error": f"Invalid timestamps: {start}-{end}"}
    if not Path(input_video).exists():
        return {"success": False, "error": f"Input video not found: {input_video}"}

    duration = end - start
    output_path = CLIPS_DIR / f"{out_name}.mp4"
    if layout is None:
        layout = "facecam" if facecam else STREAM_LAYOUT
    if layout == "facecam" and not facecam:
        layout = "zoom"

    clip_words = [
        {"word": w["word"], "start": w["start"] - start, "end": w["end"] - start}
        for w in (words or [])
        if w["start"] >= start - 0.1 and w["end"] <= end + 0.1
    ]
    caption_margin = {"facecam": 600, "fit": 380}.get(layout, OUTPUT_HEIGHT - ZOOM_TOP - ZOOM_H + 70)
    ass_path = _stream_ass(clip_words, out_name, credit, caption_margin, layout, platform)

    filters = _stream_filter(layout, facecam)
    extra_inputs = []
    if layout == "zoom" and credit:
        from overlay import socials_overlay

        png = socials_overlay(
            SUBTITLES_DIR / f"{out_name}_socials.png",
            credit,
            socials or [platform or "twitch", "youtube", "instagram", "tiktok", "x"],
            band_top=0,
            band_bottom=ZOOM_TOP,
            our_handle=OUR_HANDLE if our_handle is None else our_handle,
            bottom_band_top=ZOOM_TOP + ZOOM_H,
        )
        extra_inputs = ["-i", str(png)]
        filters = filters.replace("setsar=1[v]", "setsar=1[base]") + ";[base][1:v]overlay=0:0[v]"
    for use_subs in ([True, False] if ass_path else [False]):
        chain = filters
        if use_subs:
            escaped = str(ass_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            chain = filters + f";[v]ass={escaped}[out]"
            label = "[out]"
        else:
            label = "[v]"
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", str(start), "-i", input_video, *extra_inputs, "-t", str(duration),
            "-filter_complex", chain, "-map", label, "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(output_path),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(BASE_DIR))
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "ffmpeg timed out"}
        if proc.returncode == 0:
            return {
                "success": True,
                "filepath": str(output_path),
                "filename": output_path.name,
                "duration": round(duration, 1),
                "layout": layout,
                "has_captions": use_subs,
            }
        last_err = proc.stderr[-500:]
    return {"success": False, "error": last_err}


def _stream_filter(layout: str, facecam: list[float] | None) -> str:
    W, H = OUTPUT_WIDTH, OUTPUT_HEIGHT
    if layout == "facecam":
        x, y, w, h = facecam
        game_h = H - FACECAM_H
        return (
            "[0:v]split=2[cam_src][game_src];"
            f"[cam_src]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},"
            f"scale={W}:{FACECAM_H}:force_original_aspect_ratio=increase,crop={W}:{FACECAM_H},setsar=1[cam];"
            f"[game_src]crop=ih*{W}/{game_h}:ih,scale={W}:{game_h},setsar=1[game];"
            "[cam][game]vstack=inputs=2[v]"
        )
    bg = (f"[bg_src]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          "boxblur=25:2,eq=brightness=-0.15[bg];")
    if layout == "zoom":
        return (
            "[0:v]split=2[bg_src][fg_src];" + bg +
            f"[fg_src]scale={W}:{ZOOM_H}:force_original_aspect_ratio=increase,crop={W}:{ZOOM_H},setsar=1[fg];"
            f"[bg][fg]overlay=0:{ZOOM_TOP},setsar=1[v]"
        )
    return (
        "[0:v]split=2[bg_src][fg_src];" + bg +
        f"[fg_src]scale={W}:-2,setsar=1[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
    )


def _stream_ass(words: list, out_name: str, credit: str, caption_margin: int,
                layout: str = "fit", platform: str = "") -> Path | None:
    if not words and not credit:
        return None
    ass_path = SUBTITLES_DIR / f"{out_name}.ass"
    header = f"""[Script Info]
Title: Stream Clip
ScriptType: v4.00+
PlayResX: {OUTPUT_WIDTH}
PlayResY: {OUTPUT_HEIGHT}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Arial Black,84,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,0,2,60,60,{caption_margin},1
Style: Credit,Arial,46,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,3,2,0,8,40,40,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    if credit and layout != "zoom":  # zoom draws the credit in the socials overlay
        events.append(f"Dialogue: 1,0:00:00.00,9:59:59.00,Credit,,0,0,0,,{credit}")
    for phrase in _group_words_into_phrases(words, words_per_phrase=3):
        s = max(0.0, phrase[0]["start"])
        e = max(s + 0.2, phrase[-1]["end"])
        text = " ".join(w["word"].strip() for w in phrase).upper()
        events.append(f"Dialogue: 0,{_format_ass_time(s)},{_format_ass_time(e)},Caption,,0,0,0,,{text}")
    content = header + "\n".join(events) + "\n"
    ass_path.write_text(content.encode("utf-8", errors="replace").decode("utf-8"), encoding="utf-8")
    return ass_path
