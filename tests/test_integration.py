"""Integration tests using real ffmpeg — marked @pytest.mark.ffmpeg."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shorts.captions import generate_ass
from shorts.cutter import CutResult, cut_clip, crop_to_vertical
from shorts.highlights import Clip
from shorts.pipeline import run_pipeline


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip())


def _probe_streams(path: Path, stream_type: str) -> str:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", f"{stream_type[0]}",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return r.stdout.strip()


def _probe_dimensions(path: Path) -> tuple[int, int]:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    w, h = r.stdout.strip().split(",")
    return int(w), int(h)


def _probe_codec(path: Path, stream_type: str) -> str:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", f"{stream_type[0]}",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return r.stdout.strip()


# --- Cutter tests ---


@pytest.mark.ffmpeg
def test_cutter_produces_correct_duration(fixture_raw_dir, tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.cutter.RAW_DIR", fixture_raw_dir)
    monkeypatch.setattr("shorts.cutter.WORKING_DIR", tmp_path / "working")

    clip = Clip(start="00:00", end="00:01", slug="int-test")
    result = cut_clip("test", clip)

    assert result.video_path.exists()
    assert abs(_probe_duration(result.video_path) - 1.0) < 0.5


@pytest.mark.ffmpeg
def test_cutter_has_audio(fixture_raw_dir, tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.cutter.RAW_DIR", fixture_raw_dir)
    monkeypatch.setattr("shorts.cutter.WORKING_DIR", tmp_path / "working")

    clip = Clip(start="00:00", end="00:01", slug="audio-test")
    result = cut_clip("test", clip)

    assert "audio" in _probe_streams(result.video_path, "audio")


# --- Crop to vertical tests ---


@pytest.mark.ffmpeg
def test_crop_to_vertical_dimensions(fixture_raw_dir, tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.cutter.RAW_DIR", fixture_raw_dir)
    monkeypatch.setattr("shorts.cutter.WORKING_DIR", tmp_path / "working")

    clip = Clip(start="00:00", end="00:01", slug="dim-test")
    result = cut_clip("test", clip)

    w, h = _probe_dimensions(result.video_path)
    assert w == 1080
    assert h == 1920


@pytest.mark.ffmpeg
def test_crop_to_vertical_codec(fixture_raw_dir, tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.cutter.RAW_DIR", fixture_raw_dir)
    monkeypatch.setattr("shorts.cutter.WORKING_DIR", tmp_path / "working")

    clip = Clip(start="00:00", end="00:01", slug="codec-test")
    result = cut_clip("test", clip)

    assert _probe_codec(result.video_path, "video") == "h264"
    assert _probe_codec(result.video_path, "audio") == "aac"


@pytest.mark.ffmpeg
def test_crop_to_vertical_with_crop_region(fixture_raw_dir, tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.cutter.RAW_DIR", fixture_raw_dir)
    monkeypatch.setattr("shorts.cutter.WORKING_DIR", tmp_path / "working")

    crop = {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}
    clip = Clip(start="00:00", end="00:01", slug="crop-test", crop=crop)
    result = cut_clip("test", clip, crop=crop)

    w, h = _probe_dimensions(result.video_path)
    assert w == 1080
    assert h == 1920


# --- Pipeline tests ---


@pytest.mark.ffmpeg
def test_pipeline_integration_multi_clip(fixture_raw_dir, fixture_transcript, tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.cutter.RAW_DIR", fixture_raw_dir)
    monkeypatch.setattr("shorts.cutter.WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path / "transcripts")

    # Save transcript
    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts" / "test.json").write_text(fixture_transcript.model_dump_json())

    # Save 2 valid clips
    clips = [
        {"start": "00:00", "end": "00:01", "slug": "clip-a"},
        {"start": "00:01", "end": "00:02", "slug": "clip-b"},
    ]
    (tmp_path / "clips").mkdir()
    (tmp_path / "clips" / "test.json").write_text(json.dumps(clips))

    result = run_pipeline("test", model="unused", skip_suggest=True, log=MagicMock())

    assert result["success"] == 2
    assert result["failed"] == 0


@pytest.mark.ffmpeg
def test_pipeline_integration_partial_failure(fixture_raw_dir, fixture_transcript, tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.cutter.RAW_DIR", fixture_raw_dir)
    monkeypatch.setattr("shorts.cutter.WORKING_DIR", tmp_path / "working")
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path / "clips")
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path / "transcripts")

    (tmp_path / "transcripts").mkdir()
    (tmp_path / "transcripts" / "test.json").write_text(fixture_transcript.model_dump_json())

    # One valid clip, one beyond source duration
    clips = [
        {"start": "00:00", "end": "00:01", "slug": "good-clip"},
        {"start": "00:05", "end": "00:06", "slug": "bad-clip"},
    ]
    (tmp_path / "clips").mkdir()
    (tmp_path / "clips" / "test.json").write_text(json.dumps(clips))

    result = run_pipeline("test", model="unused", skip_suggest=True, log=MagicMock())

    assert result["success"] == 1
    assert result["failed"] == 1
