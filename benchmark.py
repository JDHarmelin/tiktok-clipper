"""
Benchmark different Claude models for the TikTok clipper pipeline.
Tests only the AI analysis phase (transcript -> clip selection -> extraction).
Skips download since we use a pre-downloaded video.
"""
import json
import time
import anthropic
from config import ANTHROPIC_API_KEY, MAX_CLIPS, MIN_CLIP_DURATION, MAX_CLIP_DURATION
from transcriber import transcribe_video

MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-sonnet-4-20250514",
    "claude-opus-4-6",
]

# Use a medium-length video already downloaded
TEST_VIDEO = "downloads/vx3vs0p6TEs.mp4"
TEST_VIDEO_ID = "vx3vs0p6TEs"

SYSTEM_PROMPT = f"""You are a TikTok content automation agent. Analyze this transcript and identify the {MAX_CLIPS} best viral clip moments.

For each clip, call extract_clip with precise start/end timestamps and a TikTok caption.

CLIP SELECTION RULES:
- Find up to {MAX_CLIPS} clips ranked by virality potential
- Each clip must be {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION} seconds
- Clips must be self-contained and make sense without context
- Strong hook in first 3 seconds is essential
- Never start or end mid-sentence
- No overlapping clips

CAPTION RULES:
- Max 150 characters including hashtags
- Always include #fyp
- NEVER include filenames or video IDs in captions

Extract clips ONE BY ONE. After all clips, provide a summary."""

TOOLS = [
    {
        "name": "extract_clip",
        "description": "Extract a clip from the source video with a TikTok caption.",
        "input_schema": {
            "type": "object",
            "properties": {
                "input_video": {"type": "string"},
                "start": {"type": "number"},
                "end": {"type": "number"},
                "clip_index": {"type": "integer"},
                "video_id": {"type": "string"},
                "caption": {"type": "string"},
            },
            "required": ["input_video", "start", "end", "clip_index", "video_id", "caption"],
        },
    },
]


def run_benchmark():
    # Step 1: Transcribe once (shared across all models)
    print("=" * 60)
    print("TRANSCRIBING VIDEO (shared across all models)...")
    print("=" * 60)
    t0 = time.time()
    transcript_result = transcribe_video(TEST_VIDEO)
    transcribe_time = time.time() - t0
    print(f"Transcription: {transcribe_time:.1f}s, {transcript_result.get('segment_count', '?')} segments")

    if not transcript_result.get("success"):
        print(f"Transcription failed: {transcript_result.get('error')}")
        return

    formatted_transcript = transcript_result["formatted_transcript"]

    # Step 2: Test each model
    results = {}
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0)

    for model in MODELS:
        print(f"\n{'=' * 60}")
        print(f"TESTING MODEL: {model}")
        print(f"{'=' * 60}")

        clips_found = []
        total_input_tokens = 0
        total_output_tokens = 0
        api_calls = 0
        errors = []

        messages = [{
            "role": "user",
            "content": f"Analyze this transcript and extract the best viral TikTok clips.\n\nVideo file: {TEST_VIDEO}\nVideo ID: {TEST_VIDEO_ID}\n\nTranscript:\n{formatted_transcript}"
        }]

        start_time = time.time()
        max_iterations = 30
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=messages,
                )
                api_calls += 1
                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens

            except anthropic.RateLimitError:
                print(f"  Rate limited, waiting 30s...")
                time.sleep(30)
                continue
            except Exception as e:
                errors.append(str(e))
                print(f"  Error: {e}")
                break

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_results = []

                for block in response.content:
                    if block.type == "tool_use" and block.name == "extract_clip":
                        inp = block.input
                        clip_duration = inp.get("end", 0) - inp.get("start", 0)
                        caption = inp.get("caption", "")
                        clips_found.append({
                            "index": inp.get("clip_index"),
                            "start": inp.get("start"),
                            "end": inp.get("end"),
                            "duration": round(clip_duration, 1),
                            "caption": caption,
                        })
                        print(f"  Clip {inp.get('clip_index')}: {inp.get('start'):.0f}s-{inp.get('end'):.0f}s ({clip_duration:.0f}s) - {caption[:60]}")

                        # Simulate success without actually running ffmpeg
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({
                                "success": True,
                                "filepath": f"clips/{TEST_VIDEO_ID}_clip_{inp.get('clip_index', 0):02d}.mp4",
                                "filename": f"{TEST_VIDEO_ID}_clip_{inp.get('clip_index', 0):02d}.mp4",
                                "duration": round(clip_duration, 1),
                                "has_captions": True,
                            }),
                        })

                messages.append({"role": "user", "content": tool_results})
            else:
                break

        elapsed = time.time() - start_time

        # Pricing per 1M tokens (as of 2025)
        pricing = {
            "claude-haiku-4-5-20251001":  {"input": 1.00, "output": 5.00},
            "claude-sonnet-4-20250514":   {"input": 3.00, "output": 15.00},
            "claude-opus-4-6":            {"input": 15.00, "output": 75.00},
        }
        p = pricing.get(model, {"input": 3.0, "output": 15.0})
        cost = (total_input_tokens * p["input"] + total_output_tokens * p["output"]) / 1_000_000

        # Check clip quality
        valid_clips = [c for c in clips_found if MIN_CLIP_DURATION <= c["duration"] <= MAX_CLIP_DURATION]
        has_filename = sum(1 for c in clips_found if "_clip_" in c["caption"] or TEST_VIDEO_ID in c["caption"])

        results[model] = {
            "time": elapsed,
            "api_calls": api_calls,
            "clips_found": len(clips_found),
            "valid_clips": len(valid_clips),
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cost": cost,
            "errors": len(errors),
            "filenames_in_captions": has_filename,
        }

        print(f"\n  Time: {elapsed:.1f}s | API calls: {api_calls} | Clips: {len(clips_found)} ({len(valid_clips)} valid)")
        print(f"  Tokens: {total_input_tokens:,} in / {total_output_tokens:,} out | Cost: ${cost:.4f}")
        if has_filename:
            print(f"  WARNING: {has_filename} captions contain filenames")

        # Wait between models to avoid rate limits
        if model != MODELS[-1]:
            print("\n  Waiting 15s before next model...")
            time.sleep(15)

    # Summary
    print(f"\n{'=' * 60}")
    print("BENCHMARK RESULTS")
    print(f"{'=' * 60}")
    print(f"{'Model':<35} {'Time':>7} {'Calls':>6} {'Clips':>6} {'Valid':>6} {'Cost':>8}")
    print("-" * 75)
    for model, r in results.items():
        name = model.split("-")[1] + "-" + model.split("-")[2]  # e.g. "haiku-4"
        print(f"{name:<35} {r['time']:>6.1f}s {r['api_calls']:>5} {r['clips_found']:>5} {r['valid_clips']:>5} ${r['cost']:>7.4f}")

    print(f"\n{'=' * 60}")
    print("RECOMMENDATION")
    print(f"{'=' * 60}")
    # Score: lower is better (weighted: 40% cost, 30% time, 30% quality)
    best = None
    best_score = float('inf')
    for model, r in results.items():
        if r['clips_found'] == 0:
            continue
        quality = r['valid_clips'] / max(r['clips_found'], 1)
        # Normalize: cost 0-1, time 0-1, quality 0-1 (inverted)
        max_cost = max(x['cost'] for x in results.values()) or 1
        max_time = max(x['time'] for x in results.values()) or 1
        score = 0.4 * (r['cost'] / max_cost) + 0.3 * (r['time'] / max_time) + 0.3 * (1 - quality)
        print(f"  {model}: score={score:.3f} (lower=better)")
        if score < best_score:
            best_score = score
            best = model

    if best:
        print(f"\n  BEST MODEL: {best}")


if __name__ == "__main__":
    run_benchmark()
