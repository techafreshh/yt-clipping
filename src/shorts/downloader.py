"""Video downloading via yt-dlp with savenow.to API fallback."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import httpx

RAW_DIR = Path("raw")
COOKIES_PATH = Path("cookies.txt")
SAVENOW_API = "https://p.savenow.to"


def _download_via_savenow(url: str, output_path: Path) -> Path:
    """Download a YouTube video via savenow.to API at1080p."""
    tmp_path = output_path.with_suffix('.tmp.mp4')
    with httpx.Client(timeout=300) as client:
        resp = client.get(f"{SAVENOW_API}/api/v2/download", params={
            "url": url,
            "format": "1080",
            "button": 1,
        })
        resp.raise_for_status()
        data = resp.json()

        if not data.get("success") or not data.get("id"):
            raise RuntimeError(f"savenow API error: {data}")

        job_id = data["id"]
        progress_url = data.get("progress_url") or f"{SAVENOW_API}/api/progress?id={job_id}"

        for _ in range(120):
            time.sleep(2)
            prog = client.get(progress_url)
            prog.raise_for_status()
            pdata = prog.json()

            if pdata.get("success") == 1 and pdata.get("download_url"):
                dl_url = pdata["download_url"]
                with client.stream("GET", dl_url, follow_redirects=True) as r:
                    r.raise_for_status()
                    with open(tmp_path, "wb") as f:
                        for chunk in r.iter_bytes(65536):
                            f.write(chunk)

                result = subprocess.run([
                    "ffmpeg", "-y", "-i", str(tmp_path),
                    "-c", "copy", "-movflags", "+faststart",
                    str(output_path),
                ], capture_output=True, text=True, check=True)
                tmp_path.unlink(missing_ok=True)
                return output_path

            if pdata.get("success") == 0 and pdata.get("text") == "Error":
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError("savenow conversion failed")

        tmp_path.unlink(missing_ok=True)
        raise RuntimeError("savenow download timed out")


def _probe_dimensions(path: Path) -> tuple[int, int]:
    """Get video width and height via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr}")

    import json
    info = json.loads(result.stdout)
    stream = info["streams"][0]
    return int(stream["width"]), int(stream["height"])


def download_youtube(url: str, name: str) -> Path:
    """Download a YouTube video. Tries savenow API first, falls back to yt-dlp."""
    out_dir = RAW_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"{name}.mp4"

    try:
        return _download_via_savenow(url, output_path)
    except Exception:
        pass

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "--postprocessor-args", "ffmpeg:-movflags +faststart",
        "-o", str(output_path),
        "--extractor-args", "youtube:player_client=web;fetch_pot=auto",
        "--extractor-args", "youtubepot-bgutilhttp:base_url=http://pot-provider:4416",
        "--remote-components", "ejs:github",
    ]
    proxy = os.environ.get("YOUTUBE_PROXY")
    if proxy:
        cmd.extend(["--proxy", proxy])
    if COOKIES_PATH.exists():
        cmd.extend(["--cookies", str(COOKIES_PATH)])
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"yt-dlp failed: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("yt-dlp not found. Install with: pip install yt-dlp")

    return output_path


def load_local_video(path: Path, name: str) -> Path:
    """Copy a local video to the raw directory. Returns path to raw video."""
    raw_dir = RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / f"{name}.mp4"

    if dest.exists() and dest.resolve() == path.resolve():
        return dest

    import shutil
    shutil.copy2(path, dest)
    return dest


def extract_audio(video_path: Path, name: str) -> Path:
    """Extract audio from a video file as WAV. Returns path to audio file."""
    raw_dir = RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    audio_path = raw_dir / f"{name}_audio.wav"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(audio_path),
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Audio extraction failed: {e.stderr}")

    return audio_path


def get_video_duration(path: Path) -> float:
    """Get video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr}")
    return float(result.stdout.strip())


def get_video_dimensions(path: Path) -> tuple[int, int]:
    """Get video width and height."""
    return _probe_dimensions(path)


def derive_name_from_url(url: str) -> str:
    """Extract a clean project name from a YouTube URL."""
    parsed = urlparse(url)
    video_id = parse_qs(parsed.query).get("v", [None])[0]
    if not video_id:
        path_parts = parsed.path.strip("/").split("/")
        video_id = path_parts[-1] if path_parts else "video"
    safe = re.sub(r"[^a-z0-9-]", "", video_id.lower())
    return safe or "video"


def derive_name_from_path(path: str) -> str:
    """Extract a clean project name from a local file path."""
    stem = Path(path).stem
    safe = re.sub(r"[^a-z0-9-]+", "-", stem.lower()).strip("-")
    return safe or "video"


def get_youtube_title(url: str) -> str | None:
    """Fetch video title from YouTube. Tries savenow API first."""
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{SAVENOW_API}/api/v2/download", params={
                "url": url,
                "format": "720",
                "button": 1,
            })
            if resp.status_code == 200:
                data = resp.json()
                title = data.get("info", {}).get("title")
                if title:
                    safe = re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-")
                    return safe[:50] if safe else None
    except Exception:
        pass

    cmd = [
        "yt-dlp",
        "--get-title",
        "--extractor-args", "youtube:player_client=web;fetch_pot=auto",
        "--extractor-args", "youtubepot-bgutilhttp:base_url=http://pot-provider:4416",
        "--remote-components", "ejs:github",
    ]
    proxy = os.environ.get("YOUTUBE_PROXY")
    if proxy:
        cmd.extend(["--proxy", proxy])
    if COOKIES_PATH.exists():
        cmd.extend(["--cookies", str(COOKIES_PATH)])
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            title = result.stdout.strip()
            safe = re.sub(r"[^a-z0-9-]+", "-", title.lower()).strip("-")
            return safe[:50] if safe else None
    except FileNotFoundError:
        pass
    return None
