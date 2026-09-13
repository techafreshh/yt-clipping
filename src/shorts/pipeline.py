"""End-to-end pipeline orchestration.

The pipeline is split into four independently callable, cache-aware steps
(``step_download``, ``step_transcript``, ``step_suggest``, ``step_cut``).
Each step reuses its on-disk artifact (raw video, transcript, clips JSON,
rendered output) unless ``force=True``. ``run_pipeline`` chains them.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

from shorts.captions import generate_ass
from shorts.config import require, settings
from shorts.cutter import cut_clip
from shorts.downloader import RAW_DIR, download_youtube, extract_audio, load_local_video, download_audio
from shorts.highlights import CLIPS_DIR, load_clips, parse_timestamp, save_clips, suggest_highlights, validate_clips
from shorts.transcript import (
    Transcript,
    fetch_transcript_with_fallback, load_cached, save_transcript,
    transcribe_video,
)


def step_download(
    name: str,
    youtube_url: Optional[str] = None,
    local_path: Optional[str] = None,
    resolution: int = 1080,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> None:
    """Step 1: download a YouTube video or copy a local video to raw/."""
    raw_path = RAW_DIR / f"{name}.mp4"
    if not force and raw_path.exists():
        log(f"  Using cached video: {raw_path}")
        return

    if youtube_url:
        download_youtube(youtube_url, name, resolution=resolution)
        log(f"  Downloaded to {raw_path}")
    elif local_path:
        load_local_video(Path(local_path), name)
        log(f"  Copied to {raw_path}")


def step_transcript(
    name: str,
    youtube_url: Optional[str] = None,
    whisper_model: str = "base",
    force: bool = False,
    log: Callable[[str], None] = print,
) -> Transcript:
    """Step 2: fetch (YouTube) or transcribe (local) the transcript, using the cache when possible."""
    if not force:
        cached = load_cached(name)
        if cached is not None:
            log("  Using cached transcript")
            return cached

    if youtube_url:
        api_key = getattr(settings, "supadata_api_key", None)
        transcript = fetch_transcript_with_fallback(youtube_url, name, api_key)
        save_transcript(name, transcript)
        log("  Fetched and saved transcript")
        return transcript

    # Local file: extract audio and transcribe with Whisper
    video_path = RAW_DIR / f"{name}.mp4"
    if not video_path.exists():
        raise RuntimeError(f"Video not found: {video_path}")
    log("  Transcribing locally with Whisper...")
    transcript = transcribe_video(video_path, name, model_name=whisper_model)
    save_transcript(name, transcript)
    log("  Transcribed and saved transcript")
    return transcript


def step_suggest(
    name: str,
    model: str = "anthropic/claude-sonnet-4",
    count: int = 5,
    context: Optional[str] = None,
    force: bool = False,
    transcript: Optional[Transcript] = None,
    log: Callable[[str], None] = print,
) -> list:
    """Step 3: AI-suggest highlights, reusing clips/{name}.json when present."""
    clips_path = CLIPS_DIR / f"{name}.json"
    if not force and clips_path.exists():
        existing = load_clips(name)
        if existing is not None:
            log(f"  Using existing clips: {clips_path}")
            return existing

    cached = transcript if transcript is not None else load_cached(name)
    if cached is None:
        raise RuntimeError("No cached transcript. Run 'shorts transcript' first.")

    api_key = require(settings, "openrouter_api_key")
    max_duration = max(seg.end for seg in cached.segments)
    clips = suggest_highlights("", api_key, model, count, segments=cached.segments, total_duration=max_duration, context=context)
    clips = validate_clips(clips, max_duration)
    save_clips(name, clips)
    log(f"  Saved {len(clips)} clips")
    return clips


def _resolve_bg_music(bg_music: Optional[str], log: Callable[[str], None] = print) -> Optional[Path]:
    """Resolve a background music URL or path to a local file, or None on failure."""
    if not bg_music:
        return None
    if bg_music.startswith(("http://", "https://")):
        log("  Resolving background music from URL...")
        try:
            return download_audio(bg_music)
        except Exception as e:
            log(f"  Warning: failed to download background music URL - {e}")
            return None
    path = Path(bg_music)
    if not path.exists():
        log(f"  Warning: background music path {bg_music} does not exist.")
        return None
    return path


def step_cut(
    name: str,
    captions: bool = False,
    remove_silence: bool = False,
    crop: Optional[dict] = None,
    title_color: Optional[str] = None,
    bg_music: Optional[str] = None,
    bg_music_volume: Optional[float] = None,
    fail_fast: bool = False,
    resume: bool = True,
    force: bool = False,
    transcript: Optional[Transcript] = None,
    youtube_url: Optional[str] = None,
    local_path: Optional[str] = None,
    webhook_url: Optional[str] = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Step 4: cut, crop, and burn every clip into output/{name}/.

    With ``resume=True`` (default), clips whose output file already exists are
    skipped, so an interrupted batch continues where it left off. Pass
    ``resume=False`` or ``force=True`` to re-render everything (e.g. after
    editing crops in clips/{name}.json).
    """
    clips = load_clips(name)
    if clips is None:
        raise RuntimeError("No clips found. Run suggest first or provide clips.")

    if remove_silence and captions:
        log("  Warning: --remove-silence and --captions together may cause sync issues. Disabling silence removal.")
        remove_silence = False

    if captions and transcript is None:
        transcript = load_cached(name)
        if transcript is None:
            raise RuntimeError("No cached transcript for captions. Run 'shorts transcript' first.")

    resolved_bg_music = _resolve_bg_music(bg_music, log=log)

    out_dir = Path("output") / name
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(clips)
    success = 0
    failed = 0
    errors: list[str] = []
    exported_clips = []

    for i, clip in enumerate(clips, 1):
        output_path = out_dir / f"{name}_short_{i:02d}_{clip.slug}.mp4"

        if resume and not force and output_path.exists():
            log(f"  Clip {i}/{total}: {clip.slug} — output exists, skipping")
            success += 1
            exported_clips.append({
                "slug": clip.slug,
                "start": clip.start,
                "end": clip.end,
                "hook": getattr(clip, "hook", ""),
                "output_path": str(output_path),
            })
            continue

        log(f"  Clip {i}/{total}: {clip.slug}")
        try:
            clip_title = getattr(clip, "hook", None)
            clip_crop = crop or (clip.crop.model_dump() if clip.crop else None)
            show_title = clip_title and (clip_crop is None)

            subtitle_path = None
            if captions or show_title:
                if captions:
                    log("    Generating subtitles...")
                else:
                    log("    Generating title...")
                subtitle_path = generate_ass(
                    name, clip.slug,
                    transcript if captions else None,
                    parse_timestamp(clip.start), parse_timestamp(clip.end),
                    title=clip_title if show_title else None,
                    title_color=title_color
                )

            log("    Rendering video (cutting, cropping, and burning captions in single pass)...")
            volume = bg_music_volume if bg_music_volume is not None else getattr(settings, "default_bg_music_volume", 0.1)
            result = cut_clip(
                name, clip, remove_silence_flag=remove_silence, crop=clip_crop,
                subtitle_path=subtitle_path, bg_music=resolved_bg_music, bg_music_volume=volume
            )

            shutil.copy2(result.video_path, output_path)
            log(f"    -> {output_path}")
            success += 1
            exported_clips.append({
                "slug": clip.slug,
                "start": clip.start,
                "end": clip.end,
                "hook": getattr(clip, "hook", ""),
                "output_path": str(output_path),
            })
        except FileNotFoundError:
            raise
        except Exception as e:
            log(f"    Warning: clip failed - {e}")
            errors.append(f"{clip.slug}: {e}")
            failed += 1
            if fail_fast:
                break
            continue

    hook_url = webhook_url or getattr(settings, "n8n_webhook_url", None)
    if hook_url:
        log("Triggering n8n webhook...")
        try:
            import httpx
            payload = {
                "video_name": name,
                "youtube_url": youtube_url or "",
                "local_path": local_path or "",
                "status": "success" if failed == 0 and success > 0 else "partial_or_failure",
                "clips_total": total,
                "clips_success": success,
                "clips_failed": failed,
                "clips": exported_clips,
                "errors": errors,
            }
            resp = httpx.post(hook_url, json=payload, timeout=15)
            log(f"  n8n webhook status: {resp.status_code}")
        except Exception as we:
            log(f"  Warning: failed to trigger n8n webhook - {we}")

    return {"total": total, "success": success, "failed": failed, "errors": errors}


def run_pipeline(
    name: str,
    youtube_url: Optional[str] = None,
    local_path: Optional[str] = None,
    model: str = "anthropic/claude-sonnet-4",
    skip_suggest: bool = False,
    fail_fast: bool = False,
    captions: bool = False,
    remove_silence: bool = False,
    extract_audio_flag: bool = False,
    crop: dict | None = None,
    whisper_model: str = "base",
    resolution: int = 1080,
    suggest_context: Optional[str] = None,
    title_color: Optional[str] = None,
    bg_music: Optional[str] = None,
    bg_music_volume: Optional[float] = None,
    force: bool = False,
    log: Callable[[str], None] = print,
) -> dict:
    """Run full pipeline: download -> transcript -> suggest -> cut.

    Cached artifacts (raw video, transcript, clips, rendered outputs) are
    reused across runs; pass ``force=True`` to bypass every cache.
    """
    steps = 4 if youtube_url or local_path else 3
    step = 0

    # Step 1: Download / Load video
    if youtube_url or local_path:
        step += 1
        log(f"[{step}/{steps}] Downloading video")
        step_download(name, youtube_url=youtube_url, local_path=local_path, resolution=resolution, force=force, log=log)

        if extract_audio_flag:
            audio_path = extract_audio(RAW_DIR / f"{name}.mp4", name)
            log(f"  Extracted audio to {audio_path}")

    # Step 2: Transcript
    step += 1
    log(f"[{step}/{steps}] Transcript")
    transcript = step_transcript(name, youtube_url=youtube_url, whisper_model=whisper_model, force=force, log=log)

    # Step 3: Suggest highlights
    step += 1
    if skip_suggest:
        log(f"[{step}/{steps}] Skipping suggest (using existing clips)")
    else:
        log(f"[{step}/{steps}] Suggesting highlights")
        step_suggest(name, model=model, context=suggest_context, force=force, transcript=transcript, log=log)

    # Step 4: Cut
    step += 1
    log(f"[{step}/{steps}] Cutting clips")
    return step_cut(
        name,
        captions=captions,
        remove_silence=remove_silence,
        crop=crop,
        title_color=title_color,
        bg_music=bg_music,
        bg_music_volume=bg_music_volume,
        fail_fast=fail_fast,
        resume=not force,
        force=force,
        transcript=transcript,
        youtube_url=youtube_url,
        local_path=local_path,
        log=log,
    )
