"""ASS subtitle generation for TikTok-style captions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shorts.transcript import Transcript, TranscriptSegment

WORKING_DIR = Path("working")


@dataclass
class CaptionWord:
    text: str
    start: float
    end: float


def _format_ass_time(seconds: float) -> str:
    """Convert float seconds to ASS time format H:MM:SS.cc."""
    if seconds < 0:
        seconds = 0.0
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _extract_words(transcript: Transcript, clip_start: float, clip_end: float) -> list[CaptionWord]:
    """Extract words within the clip window, offset to start at 0."""
    words = []

    if transcript.words:
        for w in transcript.words:
            if w.end > clip_start and w.start < clip_end:
                words.append(CaptionWord(
                    text=w.text.strip(),
                    start=max(0.0, w.start - clip_start),
                    end=max(0.0, w.end - clip_start),
                ))
    else:
        for i, seg in enumerate(transcript.segments):
            if seg.end <= clip_start or seg.start >= clip_end:
                continue

            next_start = transcript.segments[i + 1].start if i + 1 < len(transcript.segments) else float("inf")
            seg_end_cap = min(seg.end, next_start)

            seg_words = seg.text.split()
            if not seg_words:
                continue
            seg_start = max(0.0, seg.start - clip_start)
            seg_end = max(0.0, seg_end_cap - clip_start)
            seg_duration = max(seg_end - seg_start, 0.1)
            word_duration = seg_duration / len(seg_words)
            for j, word_text in enumerate(seg_words):
                w_start = seg_start + j * word_duration
                w_end = seg_start + (j + 1) * word_duration
                words.append(CaptionWord(text=word_text.strip(), start=w_start, end=w_end))

    words.sort(key=lambda w: w.start)
    return words


def _group_words(words: list[CaptionWord], max_group: int = 4, pause_threshold: float = 0.4) -> list[list[CaptionWord]]:
    """Group words into chunks of max_group, breaking on natural pauses."""
    groups: list[list[CaptionWord]] = []
    current: list[CaptionWord] = []

    for i, w in enumerate(words):
        current.append(w)

        is_last = i == len(words) - 1
        has_gap = not is_last and words[i + 1].start - w.end > pause_threshold
        is_full = len(current) >= max_group

        if is_last or has_gap or is_full:
            groups.append(list(current))
            current = []

    return groups


def generate_ass(name: str, slug: str, transcript: Transcript, clip_start: float, clip_end: float) -> Path:
    """Generate an ASS subtitle file with word-by-word highlighting."""
    words = _extract_words(transcript, clip_start, clip_end)
    groups = _group_words(words)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial Black,68,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,1,5,0,5,40,40,100,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    prev_group_end = 0.0

    for group in groups:
        if not group:
            continue

        group_start = max(group[0].start, prev_group_end)
        group_end = group[-1].end

        if group_end <= group_start:
            continue

        for wi, word in enumerate(group):
            word_start = max(word.start, group_start)

            if wi < len(group) - 1:
                word_end = group[wi + 1].start
            else:
                word_end = group_end

            word_end = max(word_end, word_start + 0.1)

            if word_end <= word_start:
                continue

            parts = []
            for wj, w in enumerate(group):
                text_upper = w.text.upper()
                if wj == wi:
                    parts.append(f"{{\\c&H00FFFF&\\b1}}{text_upper}{{\\c&HFFFFFF&\\b1}}")
                else:
                    parts.append(text_upper)
            line = " ".join(parts)

            lines.append(f"Dialogue: 0,{_format_ass_time(word_start)},{_format_ass_time(word_end)},Default,,0,0,0,,{line}")

        prev_group_end = group_end

    out_dir = WORKING_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}.ass"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
