"""Video cutter — single-track ffmpeg extraction with silence removal."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

RAW_DIR = Path("raw")
WORKING_DIR = Path("working")

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920

logger = logging.getLogger(__name__)

# GPU acceleration support
_nvenc_available: bool | None = None


def _detect_nvenc() -> bool:
    """Detect if ffmpeg has NVENC (NVIDIA GPU encoding) support."""
    global _nvenc_available
    if _nvenc_available is not None:
        return _nvenc_available
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        _nvenc_available = "h264_nvenc" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        _nvenc_available = False
    if _nvenc_available:
        logger.info("NVENC GPU encoding available — using hardware acceleration")
    else:
        logger.info("NVENC not available — using CPU encoding (libx264)")
    return _nvenc_available


def _gpu_encode_args() -> list[str]:
    """Return ffmpeg args for GPU-accelerated encoding when available, else CPU fallback."""
    if _detect_nvenc():
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "constqp", "-qp", "20"]
    return ["-c:v", "libx264", "-preset", "fast", "-crf", "18"]


def _gpu_decode_args() -> list[str]:
    """Return ffmpeg args for GPU-accelerated decoding when available."""
    if _detect_nvenc():
        return ["-hwaccel", "cuda"]
    return []


class CutResult(BaseModel):
    video_path: Path
    kept_segments: list[dict] | None = None


@dataclass
class KeptSegment:
    orig_start: float
    orig_end: float
    new_start: float


def _get_duration(path: Path) -> float:
    """Get media duration in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr}")
    return float(result.stdout.strip())


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
    info = json.loads(result.stdout)
    stream = info["streams"][0]
    return int(stream["width"]), int(stream["height"])


def _cut_track(input_path: Path, output_path: Path, start: float, end: float) -> None:
    """Cut a single track with stream-copy, falling back to re-encode if duration drifts."""
    cmd = ["ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", str(input_path), "-c", "copy", str(output_path)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg failed: {e.stderr}")

    actual = _get_duration(output_path)
    expected = end - start
    if abs(actual - expected) > 0.5:
        decode_args = _gpu_decode_args()
        encode_args = _gpu_encode_args()
        cmd = ["ffmpeg", "-y"] + decode_args + ["-ss", str(start), "-to", str(end), "-i", str(input_path),
               *encode_args, "-c:a", "aac", str(output_path)]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ffmpeg re-encode failed: {e.stderr}")


def detect_silence(video_path: Path, noise_db: float = -30.0, min_duration: float = 0.5) -> list[tuple[float, float]]:
    """Detect silent segments in a video file. Returns list of (start, end) tuples."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    starts = {}
    segments = []

    for line in result.stderr.splitlines():
        start_match = re.search(r"silence_start: ([\d.]+)", line)
        end_match = re.search(r"silence_end: ([\d.]+)", line)

        if start_match:
            starts["current"] = float(start_match.group(1))
        elif end_match and "current" in starts:
            segments.append((starts["current"], float(end_match.group(1))))
            del starts["current"]

    return segments


def remove_silence(video_path: Path, output_path: Path, silent_segments: list[tuple[float, float]]) -> list[KeptSegment]:
    """Remove silent segments from a video, returning kept segment mappings."""
    total_dur = _get_duration(video_path)

    keep_ranges: list[tuple[float, float]] = []
    cursor = 0.0

    for sil_start, sil_end in sorted(silent_segments):
        if sil_start - cursor > 0.1:
            keep_ranges.append((cursor, sil_start + 0.05))
        cursor = sil_end - 0.05
        if cursor < 0:
            cursor = 0.0

    if cursor < total_dur:
        keep_ranges.append((cursor, total_dur))

    if not keep_ranges:
        keep_ranges = [(0.0, total_dur)]

    if len(keep_ranges) == 1 and abs(keep_ranges[0][0]) < 0.01 and abs(keep_ranges[0][1] - total_dur) < 0.01:
        return []

    segments: list[KeptSegment] = []
    new_cursor = 0.0
    for orig_start, orig_end in keep_ranges:
        seg_dur = orig_end - orig_start
        if seg_dur < 0.2:
            continue
        segments.append(KeptSegment(orig_start=orig_start, orig_end=orig_end, new_start=new_cursor))
        new_cursor += seg_dur

    if not segments:
        return []

    if len(segments) == 1 and abs(segments[0].orig_start) < 0.01:
        cmd = ["ffmpeg", "-y"] + _gpu_decode_args() + ["-i", str(video_path), "-t", str(segments[0].orig_end)]
    else:
        seg_dir = output_path.parent / f"segments_{output_path.stem}"
        seg_dir.mkdir(parents=True, exist_ok=True)
        seg_paths = []
        encode_args = _gpu_encode_args()
        decode_args = _gpu_decode_args()

        for i, seg in enumerate(segments):
            seg_path = seg_dir / f"seg_{i:03d}.mp4"
            cmd = [
                "ffmpeg", "-y",
                *decode_args,
                "-ss", f"{seg.orig_start:.3f}",
                "-i", str(video_path),
                "-t", f"{seg.orig_end - seg.orig_start:.3f}",
                *encode_args,
                "-c:a", "aac",
                "-avoid_negative_ts", "make_zero",
                str(seg_path),
            ]
            try:
                subprocess.run(cmd, capture_output=True, text=True, check=True)
                seg_paths.append(seg_path)
            except subprocess.CalledProcessError:
                continue

        if not seg_paths:
            return []

        concat_file = seg_dir / "concat.txt"
        concat_lines = [f"file '{p.name}'" for p in seg_paths]
        concat_file.write_text("\n".join(concat_lines))

        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file).replace(chr(92), "/"), "-c", "copy", str(output_path).replace(chr(92), "/")]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr}")

        shutil.rmtree(seg_dir, ignore_errors=True)
        return segments

    cmd = cmd + _gpu_encode_args() + ["-c:a", "aac", str(output_path)]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg silence removal failed: {e.stderr}")

    return segments


def crop_to_vertical(input_path: Path, output_path: Path, crop: dict | None = None, subtitle_path: Path | None = None) -> None:
    """Crop/scale video to 9:16 vertical format (1080x1920).

    If crop dict is provided, crops/zooms to that region (filling the frame).
    Otherwise, scales the video to fit the container with black letterbox bars.
    Uses GPU encoding (h264_nvenc) when available, falls back to CPU (libx264).
    """
    src_w, src_h = _probe_dimensions(input_path)

    if crop:
        cx = int(crop["x"] * src_w)
        cy = int(crop["y"] * src_h)
        cw = int(crop["w"] * src_w)
        ch = int(crop["h"] * src_h)
        filter_complex = (
            f"crop={cw}:{ch}:{cx}:{cy},"
            f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"
        )
    else:
        filter_complex = (
            f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2"
        )

    if subtitle_path:
        escaped = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
        filter_complex += f",subtitles='{escaped}'"

    decode_args = _gpu_decode_args()
    encode_args = _gpu_encode_args()
    cmd = [
        "ffmpeg", "-y",
        *decode_args,
        "-i", str(input_path),
        "-vf", filter_complex,
        "-map", "0:v", "-map", "0:a?",
        *encode_args,
        "-c:a", "aac", "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Vertical crop failed: {e.stderr}")


def cut_clip(
    name: str, clip, remove_silence_flag: bool = False,
    crop: dict | None = None, subtitle_path: Path | None = None,
) -> CutResult:
    """Cut a clip from the source video, optionally remove silence, and crop to 9:16."""
    from shorts.highlights import parse_timestamp

    src_path = RAW_DIR / f"{name}.mp4"
    if not src_path.exists():
        raise FileNotFoundError(f"Missing source: {src_path}")

    start = parse_timestamp(clip.start)
    end = parse_timestamp(clip.end)

    out_dir = WORKING_DIR / name
    out_dir.mkdir(parents=True, exist_ok=True)

    cut_out = out_dir / f"{clip.slug}_cut.mp4"
    _cut_track(src_path, cut_out, start, end)

    try:
        _probe_dimensions(cut_out)
    except (RuntimeError, IndexError, KeyError):
        raise RuntimeError(f"Cut produced empty output (clip may be beyond video duration)")

    current = cut_out
    kept_segments = None

    if remove_silence_flag:
        silent = detect_silence(current)
        if silent:
            nosilence = out_dir / f"{clip.slug}_nosilence.mp4"
            kept_segments = remove_silence(current, nosilence, silent)
            if kept_segments:
                current = nosilence

    vertical_out = out_dir / f"{clip.slug}_vertical.mp4"
    crop_to_vertical(current, vertical_out, crop=crop, subtitle_path=subtitle_path)

    return CutResult(
        video_path=vertical_out,
        kept_segments=[s.__dict__ for s in kept_segments] if kept_segments else None,
    )
