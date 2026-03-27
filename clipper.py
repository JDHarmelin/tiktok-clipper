"""Extracts clips from video, reformats to 9:16 split-screen with gameplay, burns in captions."""
import random
import subprocess
from pathlib import Path
from config import OUTPUT_WIDTH, OUTPUT_HEIGHT, CLIPS_DIR, SUBTITLES_DIR, GAMEPLAY_DIR, BASE_DIR


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
