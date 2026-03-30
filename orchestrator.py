"""
Claude-powered orchestrator using Anthropic tool_use API.
Manages the full pipeline: download -> transcribe -> detect clips -> extract -> upload.
Uploads are handled programmatically after Claude finishes clip extraction.
"""
import json
import logging
import re
import anthropic
from config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    MAX_CLIPS,
    MIN_CLIP_DURATION,
    MAX_CLIP_DURATION,
)
from downloader import download_video, get_video_info, fetch_youtube_captions
from transcriber import transcribe_video
from clipper import extract_clip
from tiktok_poster import upload_to_tiktok

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0)

# ---- TOOL DEFINITIONS ----
TOOLS = [
    {
        "name": "download_youtube_video",
        "description": "Download a YouTube video given its URL. Returns filepath, title, and duration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "YouTube video URL"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "transcribe_video",
        "description": (
            "Transcribe a downloaded video file using Whisper. "
            "Returns timestamped transcript with word-level data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the video file",
                },
                "language": {
                    "type": "string",
                    "description": "Language code (optional, auto-detected)",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "extract_clip",
        "description": (
            "Extract a single clip from the source video. "
            "Reformats to 9:16 vertical with burned-in captions. "
            "Include a TikTok caption — uploads happen automatically after all clips are extracted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "input_video": {
                    "type": "string",
                    "description": "Path to source video",
                },
                "start": {
                    "type": "number",
                    "description": "Start time in seconds",
                },
                "end": {
                    "type": "number",
                    "description": "End time in seconds",
                },
                "clip_index": {
                    "type": "integer",
                    "description": "Clip number (for naming)",
                },
                "video_id": {
                    "type": "string",
                    "description": "Video ID (for naming)",
                },
                "caption": {
                    "type": "string",
                    "description": "TikTok caption with hashtags (max 150 chars). Will be used when uploading.",
                },
            },
            "required": ["input_video", "start", "end", "clip_index", "video_id", "caption"],
        },
    },
]

# Stores word data and extracted clips between steps
_pipeline_state: dict = {"words": [], "clips": [], "source_video": None, "has_captions": True}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Route tool calls to actual Python functions."""
    if tool_name == "download_youtube_video":
        result = download_video(tool_input["url"])
        if result.get("success"):
            _pipeline_state["source_video"] = result.get("filepath")
            # Check for YouTube captions immediately after download
            video_id = result.get("video_id", "")
            cap_check = fetch_youtube_captions(tool_input["url"], video_id)
            _pipeline_state["has_captions"] = cap_check.get("has_captions", True)
            result["has_captions"] = cap_check["has_captions"]
            result["caption_word_count"] = cap_check.get("word_count", 0)
            logger.info(f"Caption check: has_captions={cap_check['has_captions']}, words={cap_check.get('word_count', 0)}")
        return json.dumps(result)

    elif tool_name == "transcribe_video":
        # Skip Whisper entirely if YouTube caption check found no speech
        if not _pipeline_state.get("has_captions", True):
            logger.info("Skipping transcription — no captions detected in video")
            # Still need duration for clip selection
            try:
                import subprocess
                probe = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", tool_input["file_path"]],
                    capture_output=True, text=True, timeout=10,
                )
                total_duration = float(probe.stdout.strip()) if probe.returncode == 0 else 0
            except Exception:
                total_duration = 0
            return json.dumps({
                "success": True,
                "language": "none",
                "formatted_transcript": "[No speech detected in this video. Select clips based on visual content and pacing. No captions will be burned in.]",
                "total_duration": total_duration,
                "segment_count": 0,
                "no_speech": True,
            })

        result = transcribe_video(
            tool_input["file_path"],
            language=tool_input.get("language"),
        )
        if result.get("success"):
            _pipeline_state["words"] = result.get("words", [])
            return json.dumps({
                "success": True,
                "language": result["language"],
                "formatted_transcript": result["formatted_transcript"],
                "total_duration": result["total_duration"],
                "segment_count": len(result["segments"]),
            })
        return json.dumps(result)

    elif tool_name == "extract_clip":
        result = extract_clip(
            input_video=tool_input["input_video"],
            start=tool_input["start"],
            end=tool_input["end"],
            clip_index=tool_input["clip_index"],
            video_id=tool_input["video_id"],
            words=_pipeline_state.get("words", []),
        )
        # Track extracted clips with their captions for later upload
        if result.get("success"):
            caption = tool_input.get("caption", "")
            # Strip any filenames/clip IDs Claude may have included
            caption = _clean_caption(caption, tool_input.get("video_id", ""))
            _pipeline_state["clips"].append({
                "filepath": result["filepath"],
                "caption": caption,
                "filename": result["filename"],
            })
        return json.dumps(result)

    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})


def _clean_caption(caption: str, video_id: str) -> str:
    """Remove any filenames, clip IDs, or video IDs from the caption."""
    original = caption
    # Remove patterns like "videoId_clip_01.mp4", "videoId_clip_01" (even if glued to next word)
    caption = re.sub(r'\S*_clip_\d+\.mp4', '', caption)
    caption = re.sub(r'\S*_clip_\d+', '', caption)
    # Remove the video ID itself (e.g. "vx3vs0p6TEs")
    if video_id:
        caption = caption.replace(video_id, '')
    # Remove any remaining .mp4 references
    caption = re.sub(r'\S+\.mp4', '', caption)
    # Remove any leftover YouTube-style IDs (11 chars of alphanumeric + _ + -)
    # Require at least one digit or special char (- or _) to avoid stripping real words
    caption = re.sub(r'\b(?=[A-Za-z0-9_-]{11}\b)(?=\S*[\d_-])[A-Za-z0-9_-]{11}\b', '', caption)
    # Clean up extra spaces and leading/trailing whitespace
    caption = re.sub(r'\s+', ' ', caption).strip()
    if caption != original:
        logger.info(f"Caption cleaned: '{original}' -> '{caption}'")
    return caption


# ---- SYSTEM PROMPT ----
SYSTEM_PROMPT = f"""You are a TikTok content automation agent. Your job is to take a YouTube URL and produce viral TikTok clips.

PIPELINE (follow this exact order):
1. Download the YouTube video using download_youtube_video
   - The download result includes has_captions (bool) and caption_word_count
   - If has_captions is false, the video has NO speech — still call transcribe_video (it will skip Whisper automatically and return the duration)
2. Transcribe it using transcribe_video
   - If it returns no_speech=true or segment_count=0, proceed WITHOUT captions
   - Select clips based on video duration and even spacing across the video
3. Analyze the transcript (or video duration if no speech) to identify {MAX_CLIPS} best viral clip moments ({MIN_CLIP_DURATION}-{MAX_CLIP_DURATION}s each)
4. For each clip, call extract_clip with the precise start/end timestamps AND a TikTok caption
   - Uploads to TikTok happen AUTOMATICALLY after you finish extracting all clips
   - You do NOT need to upload manually — just provide a good caption in each extract_clip call

CLIP SELECTION RULES:
- Find up to {MAX_CLIPS} clips ranked by virality potential
- Each clip must be {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} seconds
- Clips must be self-contained and make sense without context
- Strong hook in first 3 seconds is essential
- For videos WITH speech: never start or end mid-sentence
- For videos WITHOUT speech: space clips evenly across the video duration
- No overlapping clips

CAPTION RULES (include in each extract_clip call):
- Max 150 characters including hashtags
- Always include #fyp
- Casual, engaging tone with emoji
- Encourage comments/engagement
- NEVER include filenames, clip IDs, or video IDs in captions (e.g. no "clip_01.mp4" or "YblUcJoiPdQ")

When you identify clips from the transcript, extract them ONE BY ONE by calling extract_clip for each.

If any step fails, report the error but continue with remaining clips.
At the end, provide a clear summary of how many clips were generated."""


def run_pipeline(
    youtube_url: str,
    progress_callback=None,
    account_name: str | None = None,
) -> dict:
    """
    Run the full pipeline for a YouTube URL.
    progress_callback: optional function(stage, message) for status updates.
    account_name: TikTok account to upload to (None = default).
    Returns dict with clip_count, posted_count, errors, summary.
    """
    _pipeline_state["words"] = []
    _pipeline_state["clips"] = []
    _pipeline_state["source_video"] = None
    _pipeline_state["has_captions"] = True

    # Token usage tracking
    total_input_tokens = 0
    total_output_tokens = 0

    def notify(stage, message):
        if progress_callback:
            progress_callback(stage, message)

    notify("start", f"Starting pipeline for: {youtube_url}")

    user_msg = f"Process this YouTube video into TikTok clips: {youtube_url}"
    messages = [{"role": "user", "content": user_msg}]

    max_iterations = 40
    iteration = 0

    # --- Phase 1: Claude analyzes and extracts clips ---
    while iteration < max_iterations:
        iteration += 1

        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.RateLimitError:
            import time as _time
            notify("error", "Rate limited by Anthropic API, waiting 30s...")
            _time.sleep(30)
            continue
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            import time as _time
            notify("error", f"API connection issue, retrying in 10s: {e}")
            logger.error(f"API connection error: {e}")
            _time.sleep(10)
            continue
        except anthropic.APIError as e:
            notify("error", f"Anthropic API error: {e}")
            break
        except Exception as e:
            notify("error", f"Unexpected error in pipeline loop: {e}")
            logger.error(f"Unexpected pipeline error: {e}", exc_info=True)
            break

        # Accumulate token usage from this response
        if hasattr(response, "usage") and response.usage:
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

        if response.stop_reason == "end_turn":
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text
            notify("complete", f"Claude finished: {len(_pipeline_state['clips'])} clips ready")
            break

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    notify("tool", f"Executing: {block.name}")

                    try:
                        result_str = execute_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        })

                        result_data = json.loads(result_str)
                        if block.name == "download_youtube_video" and result_data.get("success"):
                            notify("download", f"Downloaded: {result_data.get('title', 'video')}")
                        elif block.name == "transcribe_video" and result_data.get("success"):
                            notify("transcribe", f"Transcribed {result_data.get('segment_count', '?')} segments")
                        elif block.name == "extract_clip" and result_data.get("success"):
                            notify("clip", f"Clip created: {result_data.get('filename', '?')}")

                    except Exception as e:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({"error": str(e)}),
                            "is_error": True,
                        })

            messages.append({"role": "user", "content": tool_results})

        else:
            notify("error", f"Unexpected stop: {response.stop_reason}")
            break

    # --- Phase 2: Upload clips to TikTok (no Claude needed) ---
    clips = _pipeline_state["clips"]
    clip_count = len(clips)
    posted_count = 0
    verified_count = 0
    errors = []

    if clips:
        import time as _time
        from tiktok_poster import list_accounts as _list_accounts

        # Upload to all registered accounts
        all_accounts = _list_accounts()
        notify("upload", f"Uploading {clip_count} clips to {len(all_accounts)} account(s): {', '.join(all_accounts)}...")

        for acct in all_accounts:
            notify("upload", f"Uploading to account: {acct}")

            for i, clip in enumerate(clips):
                notify("upload", f"[{acct}] Uploading clip {i+1}/{clip_count}: {clip['filename']}")

                # Double-clean caption right before upload (safety net)
                video_id = clip.get("filename", "").split("_clip_")[0] if "_clip_" in clip.get("filename", "") else ""
                clean_cap = _clean_caption(clip["caption"], video_id)
                logger.info(f"[{acct}] Uploading clip {i+1}/{clip_count}: {clip['filepath']} | caption: {clean_cap}")

                result = upload_to_tiktok(
                    video_path=clip["filepath"],
                    caption=clean_cap,
                    account_name=acct,
                )

                if result.get("success"):
                    posted_count += 1
                    if result.get("verified"):
                        verified_count += 1
                        notify("upload", f"[{acct}] VERIFIED {clip['filename']}")
                    else:
                        notify("upload", f"[{acct}] Uploaded {clip['filename']} (unverified)")
                else:
                    error = result.get("error", "Unknown error")
                    errors.append(f"[{acct}] {error}")
                    screenshot = result.get("screenshot", "")
                    screenshot_msg = f" | screenshot: {screenshot}" if screenshot else ""
                    notify("error", f"[{acct}] Upload failed for {clip['filename']}: {error}{screenshot_msg}")

                    # Stop uploading to this account if rate limited
                    if result.get("rate_limited"):
                        notify("error", f"[{acct}] Rate limited — skipping remaining clips for this account")
                        break

                # Delay between uploads to avoid TikTok rate limiting
                _time.sleep(30)

    # --- Phase 3: Clean up source video to save disk space ---
    source = _pipeline_state.get("source_video")
    if source:
        from pathlib import Path
        src_path = Path(source)
        if src_path.exists():
            try:
                size_mb = src_path.stat().st_size / (1024 * 1024)
                src_path.unlink()
                notify("cleanup", f"Deleted source video ({size_mb:.0f} MB freed)")
                logger.info(f"Cleaned up source video: {source} ({size_mb:.0f} MB)")
            except Exception as e:
                logger.error(f"Failed to delete source video: {e}")

    # Calculate API cost (Claude Sonnet 4: $3/MTok input, $15/MTok output)
    input_cost = (total_input_tokens / 1_000_000) * 3.0
    output_cost = (total_output_tokens / 1_000_000) * 15.0
    total_cost = input_cost + output_cost

    return {
        "clip_count": clip_count,
        "posted_count": posted_count,
        "verified_count": verified_count,
        "errors": errors,
        "summary": f"{clip_count} clips generated, {verified_count}/{posted_count} verified on TikTok",
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "api_cost": round(total_cost, 4),
    }


def _parse_final_summary(text: str) -> dict:
    """Parse Claude's final summary text into structured data."""
    result = {"clip_count": 0, "posted_count": 0, "errors": [], "summary": text}

    clip_match = re.search(r"(\d+)\s*clips?\s*(generated|created|extracted)", text, re.I)
    if clip_match:
        result["clip_count"] = int(clip_match.group(1))

    upload_match = re.search(r"(\d+)\s*(uploaded|posted|published)", text, re.I)
    if upload_match:
        result["posted_count"] = int(upload_match.group(1))

    if "error" in text.lower() or "fail" in text.lower():
        result["errors"].append("Some steps had errors -- see summary")

    return result
