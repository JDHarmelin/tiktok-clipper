"""Claude picks the clip-worthy moments in one chunk of a stream.

One structured call per chunk: transcript + loudness spikes in, a validated list
of moments out. Code (not the model) then checks lengths, overlaps and captions.
"""
from __future__ import annotations

import logging
import re

import anthropic
from pydantic import BaseModel, Field

from config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    MIN_CLIP_DURATION,
    MAX_CLIP_DURATION,
)

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY or None, timeout=300.0)
    return _client


class Moment(BaseModel):
    start: float = Field(description="Clip start, seconds from the start of this chunk")
    end: float = Field(description="Clip end, seconds from the start of this chunk")
    title: str = Field(description="Short punchy title")
    hook: str = Field(description="What grabs attention in the first 2 seconds")
    score: int = Field(description="Virality 1-10")
    caption: str = Field(description="TikTok caption without the streamer credit or hashtags")
    hashtags: list[str] = Field(description="3-5 hashtags without the # sign")
    reason: str = Field(description="One line on why this works as a clip")


class MomentList(BaseModel):
    moments: list[Moment]


SYSTEM = """You pick short-form clips from livestreams of streamers playing GTA 6.

You get one chunk of a stream: a timestamped transcript and the seconds where the
audio spikes (yelling, laughing, chaos). Pick the moments most likely to do well
as standalone vertical clips on TikTok, Shorts and Reels.

Good GTA stream clips: chaotic police chases and crashes, big fails, funny NPC or
player interactions, the streamer's loudest genuine reactions, wild roleplay
moments, rage, unexpected payoffs. A clip should have a hook in its first two
seconds and a payoff before it ends.

Avoid: menus, loading screens, long silent driving, reading chat, ads, sponsor
reads, gambling, and anything that only makes sense with earlier context.
Avoid moments built mainly on graphic gore or killing sprees of bystanders,
since platforms limit or demonetize them.

Timing: start a beat before the hook, end just after the payoff, never cut a
sentence in half. Moments must not overlap. Return fewer moments if the chunk is
dull; an empty list is fine."""


def _user_prompt(streamer_name: str, transcript: str, spikes: list[dict], chunk_len: float,
                 max_clips: int, title: str) -> str:
    spike_lines = "\n".join(f"- {s['t']}s (loudness +{s['score']} sd)" for s in spikes) or "- none found"
    return f"""Streamer: {streamer_name}
Stream title: {title}
Chunk length: {chunk_len:.0f}s
Pick up to {max_clips} moments, each {MIN_CLIP_DURATION}-{MAX_CLIP_DURATION}s long.

Audio spikes:
{spike_lines}

Transcript:
{transcript or "[no speech detected; rely on the audio spikes]"}"""


def pick_moments(
    streamer_name: str,
    transcript: str,
    spikes: list[dict],
    chunk_len: float,
    max_clips: int,
    title: str = "",
) -> tuple[list[Moment], dict]:
    """Ask Claude for moments in this chunk. Returns (moments, usage)."""
    response = _get_client().beta.messages.parse(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": _user_prompt(
            streamer_name, transcript, spikes, chunk_len, max_clips, title)}],
        output_format=MomentList,
        output_config={"effort": "medium"},
        # If a request is ever declined, the API retries it on a fallback model
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    usage = {
        "input_tokens": getattr(response.usage, "input_tokens", 0),
        "output_tokens": getattr(response.usage, "output_tokens", 0),
    }
    if response.stop_reason == "refusal" or response.parsed_output is None:
        logger.warning(f"No moments returned (stop_reason={response.stop_reason})")
        return [], usage
    return clean_moments(response.parsed_output.moments, chunk_len, max_clips), usage


def clean_moments(moments: list[Moment], chunk_len: float, max_clips: int) -> list[Moment]:
    """Clamp to the chunk, enforce length limits, drop overlaps, best first."""
    out: list[Moment] = []
    for m in sorted(moments, key=lambda m: m.score, reverse=True):
        start = max(0.0, m.start)
        end = min(chunk_len, m.end)
        length = end - start
        if length < MIN_CLIP_DURATION:
            continue
        if length > MAX_CLIP_DURATION:
            end = start + MAX_CLIP_DURATION
        if any(start < o.end and end > o.start for o in out):
            continue
        out.append(m.model_copy(update={"start": round(start, 2), "end": round(end, 2)}))
        if len(out) >= max_clips:
            break
    return out


def build_caption(m: Moment, credit: str, max_len: int = 150) -> str:
    """Caption + streamer credit + hashtags, always crediting the streamer."""
    tags = []
    for t in ["fyp", "gta6"] + list(m.hashtags):
        t = re.sub(r"[^A-Za-z0-9_]", "", t.lstrip("#")).lower()
        if t and t not in tags:
            tags.append(t)
    tag_str = " ".join(f"#{t}" for t in tags[:6])
    body = m.caption.strip()
    credit_str = f"({credit} on stream)"
    room = max_len - len(credit_str) - len(tag_str) - 2
    if len(body) > room:
        body = body[: max(0, room - 1)].rstrip() + "…"
    return f"{body} {credit_str} {tag_str}".strip()
