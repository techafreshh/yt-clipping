"""End-to-end pipeline orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from shorts.captions import generate_ass
from shorts.config import require, settings
from shorts.cutter import cut_clip
from shorts.downloader import RAW_DIR, download_youtube, extract_audio, load_local_video
from shorts.highlights import load_clips, parse_timestamp, save_clips, suggest_highlights, validate_clips
from shorts.transcript import (
    fetch_transcript_with_fallback, load_cached, save_transcript,
    transcribe_video,
)


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
    log: Callable[[str], None] = print,
) -> dict:
    """Run full pipeline: download -> transcript -> suggest -> cut."""
    steps = 4 if youtube_url or local_path else 3
    step = 0

    # Step 1: Download / Load video
    if youtube_url or local_path:
        step += 1
        log(f"[{step}/{steps}] Downloading video")
        if youtube_url:
            download_youtube(youtube_url, name, resolution=resolution)
            log(f"  Downloaded to raw/{name}.mp4")
        else:
            load_local_video(Path(local_path), name)
            log(f"  Copied to raw/{name}.mp4")

        if extract_audio_flag:
            audio_path = extract_audio(RAW_DIR / f"{name}.mp4", name)
            log(f"  Extracted audio to {audio_path}")

    # Step 2: Transcript
    step += 1
    log(f"[{step}/{steps}] Transcript")
    cached = load_cached(name)
    if cached is None:
        api_key = getattr(settings, "supadata_api_key", None)
        if youtube_url:
            cached = fetch_transcript_with_fallback(youtube_url, name, api_key)
            save_transcript(name, cached)
            log("  Fetched and saved transcript")
        else:
            # Local file: extract audio and transcribe with Whisper
            video_path = RAW_DIR / f"{name}.mp4"
            if not video_path.exists():
                raise RuntimeError(f"Video not found: {video_path}")
            log("  Transcribing locally with Whisper...")
            cached = transcribe_video(video_path, name, model_name=whisper_model)
            save_transcript(name, cached)
            log("  Transcribed and saved transcript")
    else:
        log("  Using cached transcript")

    # Step 3: Suggest highlights
    if not skip_suggest:
        step += 1
        log(f"[{step}/{steps}] Suggesting highlights")
        api_key = require(settings, "openrouter_api_key")
        max_duration = max(seg.end for seg in cached.segments)
        clips = suggest_highlights("", api_key, model, 5, segments=cached.segments, total_duration=max_duration)
        clips = validate_clips(clips, max_duration)
        save_clips(name, clips)
        log(f"  Saved {len(clips)} clips")
    else:
        step += 1
        log(f"[{step}/{steps}] Skipping suggest (using existing clips)")

    # Step 4: Cut
    step += 1
    log(f"[{step}/{steps}] Cutting clips")

    if remove_silence and captions:
        log("  Warning: --remove-silence and --captions together may cause sync issues. Disabling silence removal.")
        remove_silence = False

    clips = load_clips(name)
    if clips is None:
        raise RuntimeError("No clips found. Run suggest first or provide clips.")

    total = len(clips)
    success = 0
    failed = 0
    errors: list[str] = []
    exported_clips = []
    for i, clip in enumerate(clips, 1):
        log(f"  Clip {i}/{total}: {clip.slug}")
        try:
            subtitle_path = None
            if captions:
                log("    Generating subtitles...")
                subtitle_path = generate_ass(name, clip.slug, cached, parse_timestamp(clip.start), parse_timestamp(clip.end))

            log("    Rendering video (cutting, cropping, and burning captions in single pass)...")
            clip_crop = crop or (clip.crop.model_dump() if clip.crop else None)
            result = cut_clip(name, clip, remove_silence_flag=remove_silence, crop=clip_crop, subtitle_path=subtitle_path)

            out_dir = Path("output") / name
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / f"{name}_short_{i:02d}_{clip.slug}.mp4"

            import shutil
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

    webhook_url = getattr(settings, "n8n_webhook_url", None)
    if webhook_url:
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
            resp = httpx.post(webhook_url, json=payload, timeout=15)
            log(f"  n8n webhook status: {resp.status_code}")
        except Exception as we:
            log(f"  Warning: failed to trigger n8n webhook - {we}")

    return {"total": total, "success": success, "failed": failed, "errors": errors}
