"""Local web UI server for the shorts editor."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Generator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from shorts.highlights import CLIPS_DIR, Clip, CropRegion, load_clips, save_clips

RAW_DIR = Path("raw")

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title="Shorts Editor")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/videos/{name}")
    def serve_video(name: str, request: Request):
        name = name.removesuffix(".mp4")
        path = RAW_DIR / f"{name}.mp4"
        if not path.exists():
            raise HTTPException(404, f"Video not found: {path}")

        file_size = path.stat().st_size
        range_header = request.headers.get("range")

        if range_header:
            start, end = _parse_range(range_header, file_size)
            length = end - start + 1
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Type": "video/mp4",
            }
            return StreamingResponse(
                _file_chunk(path, start, length),
                status_code=206,
                headers=headers,
                media_type="video/mp4",
            )

        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/clips/{name}")
    def get_clips(name: str):
        name = name.removesuffix(".mp4")
        clips = load_clips(name)
        if clips is None:
            return []
        return [c.model_dump() for c in clips]

    @app.post("/api/clips/{name}", status_code=201)
    def create_clip(name: str, clip: Clip):
        name = name.removesuffix(".mp4")
        clips = load_clips(name) or []
        clips.append(clip)
        save_clips(name, clips)
        return clip.model_dump()

    @app.put("/api/clips/{name}/{index}")
    def update_clip(name: str, index: int, clip: Clip):
        name = name.removesuffix(".mp4")
        clips = load_clips(name) or []
        if index < 0 or index >= len(clips):
            raise HTTPException(404, "Clip index out of range")
        clips[index] = clip
        save_clips(name, clips)
        return clip.model_dump()

    @app.delete("/api/clips/{name}/{index}")
    def delete_clip(name: str, index: int):
        name = name.removesuffix(".mp4")
        clips = load_clips(name) or []
        if index < 0 or index >= len(clips):
            raise HTTPException(404, "Clip index out of range")
        removed = clips.pop(index)
        save_clips(name, clips)
        return removed.model_dump()

    @app.get("/api/download-clip/{name}/{slug}")
    def download_clip(name: str, slug: str):
        name = name.removesuffix(".mp4")
        out_dir = Path("output") / name
        if not out_dir.exists():
            raise HTTPException(404, "No output directory found")

        matches = list(out_dir.glob(f"*_{slug}.mp4"))
        if not matches:
            raise HTTPException(404, f"Clip not found: {slug}")

        clip_path = matches[0]
        return FileResponse(
            clip_path,
            media_type="video/mp4",
            filename=clip_path.name,
        )

    @app.get("/api/download-all/{name}")
    def download_all(name: str):
        name = name.removesuffix(".mp4")
        out_dir = Path("output") / name
        if not out_dir.exists():
            raise HTTPException(404, "No output directory found")

        mp4_files = sorted(out_dir.glob("*.mp4"))
        if not mp4_files:
            raise HTTPException(404, "No clips found to download")

        def generate_zip():
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
                for mp4 in mp4_files:
                    zf.write(mp4, mp4.name)
            buf.seek(0)
            while chunk := buf.read(65536):
                yield chunk

        zip_filename = f"{name}_shorts.zip"
        return StreamingResponse(
            generate_zip(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
        )

    @app.get("/api/cut/{name}")
    def cut_all(name: str, captions: bool = False, crop: str = None, title_color: Optional[str] = None):
        name = name.removesuffix(".mp4")
        from shorts.captions import generate_ass
        from shorts.config import settings
        from shorts.cutter import cut_clip
        from shorts.highlights import parse_timestamp

        clips = load_clips(name)
        if not clips:
            raise HTTPException(404, "No clips found")

        # Parse global crop override (JSON string from query param)
        global_crop = None
        if crop:
            try:
                global_crop = json.loads(crop)
            except (json.JSONDecodeError, TypeError):
                pass

        transcript = None
        if captions:
            from shorts.transcript import load_cached
            transcript = load_cached(name)

        def generate() -> Generator[str, None, None]:
            success = 0
            failed = 0
            total = len(clips)
            for i, clip in enumerate(clips):
                slug = clip.slug
                yield f"data: {json.dumps({'clip': slug, 'status': 'cutting', 'index': i, 'total': total})}\n\n"
                try:
                    clip_title = getattr(clip, "hook", None)
                    clip_crop = global_crop or (clip.crop.model_dump() if clip.crop else None)
                    show_title = clip_title and (clip_crop is None)

                    subtitle_path = None
                    if (captions and transcript) or show_title:
                        subtitle_path = generate_ass(
                            name, clip.slug,
                            transcript if captions else None,
                            parse_timestamp(clip.start), parse_timestamp(clip.end),
                            title=clip_title if show_title else None,
                            title_color=title_color
                        )

                    result = cut_clip(name, clip, crop=clip_crop, subtitle_path=subtitle_path)

                    out_dir = Path("output") / name
                    out_dir.mkdir(parents=True, exist_ok=True)
                    output_path = out_dir / f"{name}_short_{i + 1:02d}_{slug}.mp4"

                    import shutil
                    shutil.copy2(result.video_path, output_path)

                    success += 1
                    yield f"data: {json.dumps({'clip': slug, 'status': 'done', 'output': str(output_path)})}\n\n"
                except Exception as e:
                    failed += 1
                    yield f"data: {json.dumps({'clip': slug, 'status': 'failed', 'error': str(e)})}\n\n"

            yield f"data: {json.dumps({'status': 'complete', 'success': success, 'failed': failed})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post("/api/download")
    async def download_video(request: Request):
        data = await request.json()
        name = data.get("name")
        youtube_url = data.get("youtube_url")
        local_path = data.get("local_path")

        if not youtube_url and not local_path:
            raise HTTPException(400, "youtube_url or local_path required")

        from shorts.downloader import (
            derive_name_from_path, derive_name_from_url,
            download_youtube, get_youtube_title, load_local_video,
        )

        try:
            if youtube_url:
                if not name:
                    title = get_youtube_title(youtube_url)
                    name = title or derive_name_from_url(youtube_url)
                download_youtube(youtube_url, name)
            else:
                if not name:
                    name = derive_name_from_path(local_path)
                load_local_video(Path(local_path), name)
        except RuntimeError as e:
            raise HTTPException(502, str(e))

        return {"status": "ok", "name": name, "path": f"raw/{name}.mp4"}

    @app.post("/api/upload")
    async def upload_video(request: Request):
        from fastapi import UploadFile, File as FastAPIFile
        from shorts.downloader import derive_name_from_path, RAW_DIR

        form = await request.form()
        file: UploadFile = form.get("file")
        name = form.get("name")

        if not file:
            raise HTTPException(400, "file required")

        if not name:
            name = derive_name_from_path(file.filename)

        raw_dir = RAW_DIR
        raw_dir.mkdir(parents=True, exist_ok=True)
        dest = raw_dir / f"{name}.mp4"

        content = await file.read()
        dest.write_bytes(content)

        return {"status": "ok", "name": name, "path": f"raw/{name}.mp4"}

    @app.post("/api/cookies")
    async def upload_cookies(request: Request):
        from fastapi import UploadFile, File as FastAPIFile
        from shorts.downloader import COOKIES_PATH

        form = await request.form()
        file: UploadFile = form.get("file")

        if not file:
            raise HTTPException(400, "file required")

        content = await file.read()
        COOKIES_PATH.write_bytes(content)

        return {"status": "ok", "message": "Cookies saved", "path": str(COOKIES_PATH)}

    @app.get("/api/cookies")
    async def get_cookies_status():
        from shorts.downloader import COOKIES_PATH
        exists = COOKIES_PATH.exists()
        return {"exists": exists, "path": str(COOKIES_PATH)}

    @app.delete("/api/cookies")
    async def delete_cookies():
        from shorts.downloader import COOKIES_PATH
        if COOKIES_PATH.exists():
            COOKIES_PATH.unlink()
        return {"status": "ok", "message": "Cookies deleted"}

    @app.post("/api/auto/transcript")
    async def auto_transcript(request: Request):
        data = await request.json()
        name = data.get("name")
        youtube_url = data.get("youtube_url")
        whisper_model = data.get("whisper_model", "base")

        if not name:
            raise HTTPException(400, "name required")

        from shorts.config import settings
        from shorts.transcript import (
            fetch_transcript_with_fallback, load_cached, save_transcript,
            transcribe_video,
        )

        cached = load_cached(name)
        if cached and not data.get("force"):
            return {"status": "cached", "segments": len(cached.segments)}

        if youtube_url:
            api_key = getattr(settings, "supadata_api_key", None)
            try:
                result = fetch_transcript_with_fallback(youtube_url, name, api_key)
            except RuntimeError as e:
                raise HTTPException(502, str(e))
            save_transcript(name, result)
            return {"status": "fetched", "segments": len(result.segments)}
        else:
            # Local file transcription with Whisper
            video_path = RAW_DIR / f"{name}.mp4"
            if not video_path.exists():
                raise HTTPException(404, f"Video not found: raw/{name}.mp4. Upload or download a video first.")
            try:
                result = transcribe_video(video_path, name, model_name=whisper_model)
            except RuntimeError as e:
                raise HTTPException(502, str(e))
            save_transcript(name, result)
            return {"status": "transcribed", "segments": len(result.segments)}

    @app.post("/api/auto/suggest")
    async def auto_suggest(request: Request):
        data = await request.json()
        name = data.get("name")
        count = data.get("count", 5)
        model = data.get("model")
        context = data.get("context")

        if not name:
            raise HTTPException(400, "name required")

        from shorts.config import require, settings
        from shorts.highlights import suggest_highlights, validate_clips
        from shorts.transcript import load_cached

        cached = load_cached(name)
        if cached is None:
            raise HTTPException(404, "No transcript found. Fetch transcript first.")

        api_key = require(settings, "openrouter_api_key")
        use_model = model or settings.default_model
        max_duration = max(seg.end for seg in cached.segments)

        try:
            clips = suggest_highlights(
                "", api_key, use_model, count,
                segments=cached.segments, total_duration=max_duration,
                context=context
            )
            clips = validate_clips(clips, max_duration)
        except (RuntimeError, ValueError) as e:
            raise HTTPException(502, str(e))

        save_clips(name, clips)
        return {"status": "ok", "count": len(clips), "clips": [c.model_dump() for c in clips]}

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


app = create_app()


def _parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    """Parse HTTP Range header, return (start, end) byte positions."""
    range_spec = range_header.replace("bytes=", "")
    parts = range_spec.split("-")
    start = int(parts[0]) if parts[0] else 0
    end = int(parts[1]) if parts[1] else file_size - 1
    end = min(end, file_size - 1)
    return start, end


def _file_chunk(path: Path, start: int, length: int, chunk_size: int = 65536) -> Generator[bytes, None, None]:
    """Yield file chunks from a given offset."""
    with open(path, "rb") as f:
        f.seek(start)
        remaining = length
        while remaining > 0:
            read_size = min(chunk_size, remaining)
            data = f.read(read_size)
            if not data:
                break
            remaining -= len(data)
            yield data
