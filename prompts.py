"""All prompt templates for Claude AI interactions."""

VIRAL_CLIP_DETECTION_PROMPT = """You are an expert TikTok/Shorts content strategist. Analyze this transcript and identify the {max_clips} BEST segments for viral short-form clips.

TRANSCRIPT:
{transcript}

VIDEO TITLE: {title}
TOTAL DURATION: {duration}s

RULES:
- Each clip must be {min_duration}-{max_duration} seconds long
- Clips must be SELF-CONTAINED (make sense without context from the rest of the video)
- Never start or end mid-sentence -- find natural boundaries
- Add 1-2 seconds of padding before/after the core moment
- No two clips should overlap in timestamps
- Rank by virality potential (best first)

WHAT MAKES A CLIP GO VIRAL:
- Strong hook in first 3 seconds (bold claim, question, surprising stat, conflict)
- Emotional peak (funny, shocking, inspiring, controversial, relatable)
- Clear payoff or punchline within the clip
- "Quotable" or shareable moment
- High speaker energy or passion
- Pattern interrupts or unexpected turns

AVOID:
- Intros, outros, sponsor segments
- Rambling without a clear point
- Heavy context-dependent segments
- Sections that are mostly filler or pleasantries

Return ONLY a JSON array (no markdown, no explanation):
[
  {{
    "start": 125.4,
    "end": 178.2,
    "title": "Short punchy title for this clip",
    "hook": "The attention-grabbing opening line",
    "virality_score": 9,
    "category": "shocking",
    "caption": "TikTok caption with #hashtags (max 150 chars)",
    "reasoning": "Brief explanation of why this will go viral"
  }}
]"""

CAPTION_GENERATION_PROMPT = """Generate a TikTok caption for this video clip.

CLIP TITLE: {title}
CLIP TRANSCRIPT: {transcript}
CATEGORY: {category}

Requirements:
- Max 150 characters including hashtags
- Include 3-5 relevant hashtags (#fyp is mandatory)
- Use engaging, casual tone
- Add relevant emoji
- Make it encourage comments/engagement

Return ONLY the caption text, nothing else."""
