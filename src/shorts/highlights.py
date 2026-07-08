"""AI highlight suggestions via OpenRouter."""

from __future__ import annotations

import json
import re
import time
import warnings
from pathlib import Path
from typing import Optional

import httpx
from pydantic import BaseModel, field_validator

CLIPS_DIR = Path("clips")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class CropRegion(BaseModel):
    """Normalized crop region (0.0-1.0 relative to source dimensions)."""
    x: float
    y: float
    w: float
    h: float


class Clip(BaseModel):
    start: str
    end: str
    slug: str
    hook: Optional[str] = None
    crop: Optional[CropRegion] = None

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9-]+$", v):
            safe = re.sub(r"[^a-z0-9-]+", "-", v.lower()).strip("-")
            raise ValueError(f"slug must match ^[a-z0-9-]+$; try '{safe}' instead")
        return v


def parse_timestamp(ts: str) -> float:
    """Parse HH:MM:SS, MM:SS, or raw seconds into float seconds."""
    parts = ts.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(ts)


def validate_clips(clips: list[Clip], max_duration: float) -> list[Clip]:
    """Validate clips against transcript bounds. Raises ValueError on invalid clips."""
    valid = []
    for clip in clips:
        start = parse_timestamp(clip.start)
        end = parse_timestamp(clip.end)
        if end <= start:
            raise ValueError(f"Clip '{clip.slug}': end ({clip.end}) <= start ({clip.start})")
        if end > max_duration:
            raise ValueError(f"Clip '{clip.slug}': end ({clip.end}) exceeds transcript duration ({max_duration}s)")
        duration = end - start
        if duration < 5 or duration > 300:
            warnings.warn(f"Clip '{clip.slug}' duration {duration:.1f}s outside 5-300s range", stacklevel=2)
        valid.append(clip)
    return valid


def _format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS for display in prompts."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}:{s:02d}"


def suggest_highlights(
    transcript_text: str,
    api_key: str,
    model: str,
    count: int,
    segments: list | None = None,
    total_duration: float | None = None,
    context: str | None = None,
) -> list[Clip]:
    """Call OpenRouter LLM to suggest clip-worthy highlights from transcript.

    The AI decides how many clips to return (up to `count` max).
    """
    duration_hint = ""
    if total_duration is not None:
        duration_hint = f"The video is {_format_timestamp(total_duration)} long ({total_duration:.0f} seconds).\n"

    system_prompt = (
        "You are a podcast/video clip editor. Given a transcript, identify the best clip-worthy moments.\n"
        f"{duration_hint}\n"
        "RULES:\n"
        "1. You decide how many clips to suggest — only include moments that are truly compelling.\n"
        f"2. Return at most {count} clips. Quality over quantity — it's better to return fewer great clips than many mediocre ones.\n"
        "3. Each clip MUST be between 30 and 300 seconds long.\n"
        "4. Use timestamps from the transcript. end minus start >= 30.\n"
        "5. Each clip must have a strong opening hook that grabs attention in the first 3 seconds.\n"
        "6. CRITICAL — NEVER cut mid-sentence. Every clip must start at the beginning of a sentence or paragraph "
        "and end at a natural sentence/paragraph boundary. Look for periods, question marks, exclamation marks, "
        "or paragraph breaks in the transcript to identify safe cut points. "
        "If a sentence spans across your desired cut point, extend the clip to include the full sentence.\n"
        "7. Look for: emotional moments, funny moments, controversial opinions, surprising facts, high energy delivery.\n"
        "8. These clips will be exported as vertical 9:16 format for podcast clips.\n"
        "\n"
        'Return JSON: {"clips": [{"start": "MM:SS", "end": "MM:SS", "slug": "kebab-case-name", "hook": "one-line hook"}]}.\n'
        "start and end are timestamps in MM:SS format. Each clip must be at least 30 seconds."
    )

    if context:
        system_prompt += f"\n\nADDITIONAL VIDEO CONTEXT & EDITING DIRECTIONS:\n{context.strip()}"

    user_content = transcript_text
    if segments and total_duration is not None:
        ts_lines = []
        for seg in segments:
            ts_lines.append(f"[{_format_timestamp(seg.start)} - {_format_timestamp(seg.end)}] {seg.text}")
        user_content = "\n".join(ts_lines)

    payload = {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    with httpx.Client(timeout=60) as client:
        for attempt in range(2):
            resp = client.post(OPENROUTER_URL, json=payload, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(f"OpenRouter API error {resp.status_code}: {resp.text}")
            try:
                data = json.loads(resp.json()["choices"][0]["message"]["content"])
                return [Clip(**c) for c in data["clips"]]
            except (json.JSONDecodeError, KeyError, TypeError):
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise RuntimeError(f"Failed to parse LLM response after retry: {resp.text}")


def save_clips(name: str, clips: list[Clip]) -> Path:
    """Save clips to disk as JSON."""
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    path = CLIPS_DIR / f"{name}.json"
    path.write_text(json.dumps([c.model_dump() for c in clips], indent=2))
    return path


def load_clips(name: str) -> list[Clip] | None:
    """Load clips from disk, or None if not found."""
    path = CLIPS_DIR / f"{name}.json"
    if path.exists():
        return [Clip(**c) for c in json.loads(path.read_text())]
    return None
