"""Transcript fetching via Supadata API with yt-dlp fallback, or local Whisper transcription."""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import warnings
from pathlib import Path
from typing import Optional

import httpx
from pydantic import BaseModel

TRANSCRIPTS_DIR = Path("transcripts")
API_URL = "https://api.supadata.ai/v1/transcript"


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class Transcript(BaseModel):
    segments: list[TranscriptSegment]
    words: Optional[list[TranscriptSegment]] = None


def _parse_segment(raw: dict) -> TranscriptSegment:
    """Parse a segment from either start/end or offset/duration format."""
    if "start" in raw and "end" in raw:
        return TranscriptSegment(start=raw["start"], end=raw["end"], text=raw["text"])
    offset = raw.get("offset", 0)
    duration = raw.get("duration", 0)
    return TranscriptSegment(start=offset / 1000.0, end=(offset + duration) / 1000.0, text=raw["text"])


def fetch_transcript(youtube_url: str, api_key: str) -> Transcript:
    """Fetch transcript from Supadata API with one retry on 5xx."""
    with httpx.Client(timeout=30) as client:
        for attempt in range(2):
            resp = client.get(
                API_URL,
                params={"url": youtube_url},
                headers={"x-api-key": api_key},
            )
            if resp.status_code >= 500 and attempt == 0:
                time.sleep(2)
                continue
            break

        if resp.status_code != 200:
            raise RuntimeError(
                f"Supadata API error {resp.status_code}: {resp.text}. Check your API key."
            )

        data = resp.json()
        segments = [_parse_segment(s) for s in data.get("content", [])]
        words = None
        if data.get("words"):
            words = [_parse_segment(w) for w in data["words"]]
        return Transcript(segments=segments, words=words)


def fetch_transcript_ytdlp(youtube_url: str, name: str) -> Transcript:
    """Fetch subtitles via yt-dlp as fallback when Supadata is unavailable."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_template = str(Path(tmpdir) / f"{name}.%(ext)s")
            cmd = [
                "yt-dlp",
                "--write-auto-sub",
                "--sub-lang", "en",
                "--skip-download",
                "--sub-format", "json3",
                "--extractor-args", "youtube:player_client=web;fetch_pot=auto",
                "--extractor-args", "youtubepot-bgutilhttp:base_url=http://pot-provider:4416",
                "--remote-components", "ejs:github",
                "-o", out_template,
            ]
            import os
            proxy = os.environ.get("YOUTUBE_PROXY")
            if proxy:
                cmd.extend(["--proxy", proxy])
            from shorts.downloader import COOKIES_PATH
            if COOKIES_PATH.exists():
                cmd.extend(["--cookies", str(COOKIES_PATH)])
            cmd.append(youtube_url)
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"yt-dlp subtitle download failed: {result.stderr}")

            json3_path = Path(tmpdir) / f"{name}.en.json3"
            if not json3_path.exists():
                raise RuntimeError("No subtitles found for this video")

            import json
            data = json.loads(json3_path.read_text())
            events = data.get("events", [])

            segments: list[TranscriptSegment] = []
            for event in events:
                if "segs" not in event:
                    continue
                start_ms = event.get("tStartMs", 0)
                dur_ms = event.get("dDurationMs", 0)
                text = "".join(seg.get("utf8", "") for seg in event["segs"]).strip()
                if text:
                    segments.append(TranscriptSegment(
                        start=start_ms / 1000.0,
                        end=(start_ms + dur_ms) / 1000.0,
                        text=text,
                    ))

            if not segments:
                raise RuntimeError("Subtitles file was empty or unparseable")

            return Transcript(segments=segments)
    except FileNotFoundError:
        raise RuntimeError("yt-dlp not found. Install with: pip install yt-dlp")


def fetch_transcript_with_fallback(youtube_url: str, name: str, api_key: str | None = None) -> Transcript:
    """Try Supadata first, fall back to yt-dlp subtitles."""
    if api_key:
        try:
            return fetch_transcript(youtube_url, api_key)
        except RuntimeError:
            pass

    return fetch_transcript_ytdlp(youtube_url, name)


def load_cached(name: str) -> Transcript | None:
    """Load cached transcript from disk, or None if not found."""
    path = TRANSCRIPTS_DIR / f"{name}.json"
    if path.exists():
        return Transcript.model_validate_json(path.read_text())
    return None


def load_from_file(file_path: Path) -> Transcript:
    """Load transcript from a local JSON or plain text file."""
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if file_path.suffix == ".json":
        return Transcript.model_validate_json(file_path.read_text())
    content = file_path.read_text()
    warnings.warn("Plain text file loaded — timestamps are approximate", stacklevel=2)
    return Transcript(segments=[TranscriptSegment(start=0.0, end=0.0, text=content)])


def save_transcript(name: str, transcript: Transcript) -> Path:
    """Save transcript to disk and return the file path."""
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPTS_DIR / f"{name}.json"
    path.write_text(transcript.model_dump_json(indent=2))
    return path


def transcribe_local_audio(audio_path: Path, model_name: str = "base") -> Transcript:
    """Transcribe a local audio file using Whisper.

    Args:
        audio_path: Path to the audio file (WAV, MP3, etc.)
        model_name: Whisper model size (tiny, base, small, medium, large)
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    try:
        import whisper
    except ImportError:
        raise RuntimeError(
            "Whisper not installed. Install with: uv pip install openai-whisper"
        )

    try:
        model = whisper.load_model(model_name)
        result = model.transcribe(str(audio_path), word_timestamps=True)

        segments: list[TranscriptSegment] = []
        words: list[TranscriptSegment] = []

        for seg in result.get("segments", []):
            segments.append(TranscriptSegment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
            ))
            for w in seg.get("words", []):
                words.append(TranscriptSegment(
                    start=w["start"],
                    end=w["end"],
                    text=w["word"].strip(),
                ))

        return Transcript(
            segments=segments,
            words=words if words else None,
        )
    except Exception as e:
        raise RuntimeError(f"Whisper transcription failed: {e}")


def transcribe_video(video_path: Path, name: str, model_name: str = "base") -> Transcript:
    """Extract audio from video and transcribe with Whisper."""
    from shorts.downloader import RAW_DIR, extract_audio

    audio_path = RAW_DIR / f"{name}_audio.wav"
    if not audio_path.exists():
        audio_path = extract_audio(video_path, name)

    return transcribe_local_audio(audio_path, model_name=model_name)
