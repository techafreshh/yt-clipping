"""CLI entry point for the shorts tool."""

from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(help="YouTube clipper — download, suggest highlights, and export vertical shorts.")


@app.command()
def download(
    name: Optional[str] = typer.Argument(None, help="Source name identifier (auto-derived if omitted)"),
    youtube_url: Optional[str] = typer.Option(None, "--youtube-url", help="YouTube video URL to download"),
    local_path: Optional[str] = typer.Option(None, "--local-path", help="Local video file path to use"),
    audio: bool = typer.Option(False, "--audio", help="Also extract audio as WAV"),
    resolution: int = typer.Option(1080, "--resolution", help="Preferred video resolution (e.g. 1080, 720)"),
):
    """Download a YouTube video or copy a local video to raw/."""
    from shorts.downloader import (
        derive_name_from_path, derive_name_from_url, download_youtube,
        extract_audio, get_youtube_title, load_local_video, RAW_DIR,
    )

    if youtube_url and local_path:
        raise typer.BadParameter("Provide --youtube-url or --local-path, not both")
    if not youtube_url and not local_path:
        raise typer.BadParameter("Provide --youtube-url or --local-path")

    if not name:
        if youtube_url:
            title = get_youtube_title(youtube_url)
            name = title or derive_name_from_url(youtube_url)
        else:
            name = derive_name_from_path(local_path)
        typer.echo(f"Project name: {name}")

    try:
        if youtube_url:
            path = download_youtube(youtube_url, name, resolution=resolution)
            typer.echo(f"Downloaded to {path}")
        else:
            path = load_local_video(Path(local_path), name)
            typer.echo(f"Copied to {path}")

        if audio:
            audio_path = extract_audio(RAW_DIR / f"{name}.mp4", name)
            typer.echo(f"Extracted audio to {audio_path}")
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def transcript(
    name: str = typer.Argument(..., help="Source name identifier"),
    youtube_url: Optional[str] = typer.Option(None, "--youtube-url", help="YouTube video URL to fetch transcript from"),
    from_file: Optional[str] = typer.Option(None, "--from-file", help="Local transcript file path (JSON or .txt)"),
    local_video: Optional[str] = typer.Option(None, "--local-video", help="Local video file to transcribe with Whisper"),
    whisper_model: str = typer.Option("base", "--whisper-model", help="Whisper model size (tiny/base/small/medium/large)"),
    force: bool = typer.Option(False, "--force", help="Re-fetch even if cached"),
):
    """Fetch or load a transcript for a video."""
    sources = sum(1 for x in [youtube_url, from_file, local_video] if x)
    if sources > 1:
        raise typer.BadParameter("Provide only one of --youtube-url, --from-file, or --local-video")
    if sources == 0:
        raise typer.BadParameter("Provide --youtube-url, --from-file, or --local-video")

    if from_file:
        from shorts.transcript import load_from_file, save_transcript

        try:
            result = load_from_file(Path(from_file))
        except FileNotFoundError as e:
            raise typer.BadParameter(str(e))
        path = save_transcript(name, result)
        typer.echo(f"Transcript saved to {path}")
        return

    if local_video:
        from shorts.downloader import RAW_DIR
        from shorts.transcript import load_cached, save_transcript, transcribe_video

        video_path = Path(local_video)
        if not video_path.exists():
            raise typer.BadParameter(f"Video file not found: {local_video}")

        # Copy to raw/ if not already there
        from shorts.downloader import load_local_video
        raw_path = RAW_DIR / f"{name}.mp4"
        if not raw_path.exists() or raw_path.resolve() != video_path.resolve():
            load_local_video(video_path, name)
            typer.echo(f"Copied video to raw/{name}.mp4")

        if not force:
            cached = load_cached(name)
            if cached is not None:
                typer.echo("Using cached transcript")
                return

        typer.echo(f"Transcribing with Whisper ({whisper_model})...")
        try:
            result = transcribe_video(raw_path, name, model_name=whisper_model)
        except RuntimeError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

        path = save_transcript(name, result)
        typer.echo(f"Transcript saved to {path}")
        return

    from shorts.config import settings
    from shorts.transcript import fetch_transcript_with_fallback, load_cached, save_transcript

    if not force:
        cached = load_cached(name)
        if cached is not None:
            typer.echo("Using cached transcript")
            return

    api_key = getattr(settings, "supadata_api_key", None)
    try:
        result = fetch_transcript_with_fallback(youtube_url, name, api_key)
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    path = save_transcript(name, result)
    typer.echo(f"Transcript saved to {path}")


@app.command()
def suggest(
    name: str = typer.Argument(..., help="Source name identifier"),
    model: Optional[str] = typer.Option(None, "--model", help="OpenRouter model to use"),
    count: int = typer.Option(5, "--count", help="Number of clips to suggest"),
):
    """AI-suggest clip-worthy highlights from a transcript."""
    from shorts.config import require, settings
    from shorts.highlights import save_clips, suggest_highlights, validate_clips
    from shorts.transcript import load_cached

    cached = load_cached(name)
    if cached is None:
        typer.echo("Error: no cached transcript. Run 'shorts transcript' first.", err=True)
        raise typer.Exit(1)

    api_key = require(settings, "openrouter_api_key")
    use_model = model or settings.default_model
    max_duration = max(seg.end for seg in cached.segments)

    try:
        clips = suggest_highlights("", api_key, use_model, count, segments=cached.segments, total_duration=max_duration)
        clips = validate_clips(clips, max_duration)
    except (RuntimeError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    path = save_clips(name, clips)
    typer.echo(f"Saved {len(clips)} clips to {path}")


@app.command()
def cut(
    name: str = typer.Argument(..., help="Source name identifier"),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop on first clip failure"),
    captions: bool = typer.Option(False, "--captions", help="Burn TikTok-style captions"),
    remove_silence: bool = typer.Option(False, "--remove-silence", help="Remove silent gaps for tighter pacing"),
    audio: bool = typer.Option(False, "--audio", help="Export audio alongside video clips"),
):
    """Cut and export vertical shorts from clip specs."""
    from shorts.cutter import cut_clip
    from shorts.downloader import RAW_DIR, extract_audio
    from shorts.highlights import load_clips, parse_timestamp

    clips = load_clips(name)
    if clips is None:
        typer.echo("Error: no clips found. Run 'shorts suggest' first.", err=True)
        raise typer.Exit(1)

    transcript = None
    if captions:
        from shorts.captions import generate_ass
        from shorts.transcript import load_cached

        transcript = load_cached(name)
        if transcript is None:
            typer.echo("Error: No cached transcript for captions. Run 'shorts transcript' first.", err=True)
            raise typer.Exit(1)

    if remove_silence and captions:
        typer.echo("Warning: --remove-silence and --captions together may cause sync issues. Using captions without silence removal.", err=True)
        remove_silence = False

    success = 0
    errors: list[str] = []
    for i, clip in enumerate(clips, 1):
        typer.echo(f"Cutting clip {i}/{len(clips)}: {clip.slug}")
        subtitle_path = None
        if captions:
            subtitle_path = generate_ass(name, clip.slug, transcript, parse_timestamp(clip.start), parse_timestamp(clip.end))

        try:
            clip_crop = clip.crop.model_dump() if clip.crop else None
            result = cut_clip(name, clip, remove_silence_flag=remove_silence, crop=clip_crop, subtitle_path=subtitle_path)
        except FileNotFoundError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        except RuntimeError as e:
            typer.echo(f"Warning: {e}", err=True)
            errors.append(f"{clip.slug}: {e}")
            if fail_fast:
                break
            continue

        try:
            from shorts.cutter import WORKING_DIR
            out_dir = Path("output") / name
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / f"{name}_short_{i:02d}_{clip.slug}.mp4"

            import shutil
            shutil.copy2(result.video_path, output_path)
            typer.echo(f"  -> {output_path}")

            if audio:
                audio_out = out_dir / f"{name}_short_{i:02d}_{clip.slug}_audio.wav"
                extract_audio(output_path, f"{name}_short_{i:02d}_{clip.slug}_audio")
                import shutil as _shutil
                _shutil.move(str(RAW_DIR / f"{name}_short_{i:02d}_{clip.slug}_audio.wav"), str(audio_out))

            success += 1
        except RuntimeError as e:
            typer.echo(f"Warning: export failed: {e}", err=True)
            errors.append(f"{clip.slug}: {e}")
            if fail_fast:
                break

    if errors:
        for err in errors:
            typer.echo(f"  FAILED: {err}", err=True)
        typer.echo(f"Done: {success}/{len(clips)} clips exported, {len(errors)} failed")
        raise typer.Exit(1)

    typer.echo(f"Done: {success}/{len(clips)} clips exported")


@app.command()
def run(
    name: Optional[str] = typer.Argument(None, help="Source name identifier (auto-derived if omitted)"),
    youtube_url: Optional[str] = typer.Option(None, "--youtube-url", help="YouTube URL for video + transcript"),
    local_path: Optional[str] = typer.Option(None, "--local-path", help="Local video file path"),
    model: Optional[str] = typer.Option(None, "--model", help="OpenRouter model"),
    skip_suggest: bool = typer.Option(False, "--skip-suggest", help="Use existing clips"),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop on first clip failure"),
    captions: bool = typer.Option(False, "--captions", help="Burn TikTok-style captions"),
    remove_silence: bool = typer.Option(False, "--remove-silence", help="Remove silent gaps for tighter pacing"),
    audio: bool = typer.Option(False, "--audio", help="Extract audio for podcast clips"),
    whisper_model: str = typer.Option("base", "--whisper-model", help="Whisper model for local transcription (tiny/base/small/medium/large)"),
    resolution: int = typer.Option(1080, "--resolution", help="Preferred video resolution (e.g. 1080, 720)"),
):
    """Run the full pipeline end-to-end."""
    from shorts.config import settings
    from shorts.downloader import derive_name_from_path, derive_name_from_url, get_youtube_title
    from shorts.pipeline import run_pipeline

    use_model = model or settings.default_model

    if not name:
        if youtube_url:
            title = get_youtube_title(youtube_url)
            name = title or derive_name_from_url(youtube_url)
        elif local_path:
            name = derive_name_from_path(local_path)
        elif not skip_suggest:
            typer.echo("Error: Provide a name, --youtube-url, or --local-path.", err=True)
            raise typer.Exit(1)
        else:
            typer.echo("Error: Provide a name or --skip-suggest with existing clips.", err=True)
            raise typer.Exit(1)
        typer.echo(f"Project name: {name}")

    if not skip_suggest and not youtube_url and not local_path:
        from shorts.transcript import load_cached
        cached = load_cached(name)
        if cached is None:
            typer.echo("Error: No cached transcript. Provide --youtube-url, --local-path, or use --skip-suggest.", err=True)
            raise typer.Exit(1)

    try:
        summary = run_pipeline(
            name,
            youtube_url=youtube_url,
            local_path=local_path,
            model=use_model,
            skip_suggest=skip_suggest,
            fail_fast=fail_fast,
            captions=captions,
            remove_silence=remove_silence,
            extract_audio_flag=audio,
            whisper_model=whisper_model,
            resolution=resolution,
            log=typer.echo,
        )
    except (RuntimeError, FileNotFoundError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if summary.get("failed", 0) > 0:
        for err in summary.get("errors", []):
            typer.echo(f"  FAILED: {err}", err=True)
        typer.echo(f"Done: {summary['success']}/{summary['total']} clips produced, {summary['failed']} failed")
        raise typer.Exit(1)

    typer.echo(f"Done: {summary['success']}/{summary['total']} clips produced")


@app.command()
def config():
    """Print resolved configuration (secrets masked)."""
    from shorts.config import mask, settings

    for name in settings.model_fields:
        value = getattr(settings, name)
        if value is not None and ("key" in name or "api" in name):
            typer.echo(f"{name.upper()}: {mask(str(value))}")
        else:
            typer.echo(f"{name.upper()}: {value}")


@app.command()
def serve(
    port: int = typer.Option(8000, "--port", help="Port to listen on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
):
    """Start the local web UI server."""
    import uvicorn

    from shorts.server import create_app

    application = create_app()
    typer.echo(f"Starting shorts editor at http://{host}:{port}")
    uvicorn.run(application, host=host, port=port)
