"""Tests for the cutter module."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from shorts.cli import app
from shorts.cutter import CutResult, KeptSegment, _cut_track, _get_duration, crop_to_vertical, cut_clip, detect_silence, remove_silence
from shorts.highlights import Clip

runner = CliRunner()


# --- _get_duration ---


def test_get_duration_success(monkeypatch):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "45.5\n"
    monkeypatch.setattr("shorts.cutter.subprocess.run", lambda *a, **kw: mock_result)
    assert _get_duration(Path("test.mp4")) == 45.5


def test_get_duration_failure(monkeypatch):
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "No such file"
    monkeypatch.setattr("shorts.cutter.subprocess.run", lambda *a, **kw: mock_result)
    with pytest.raises(RuntimeError, match="ffprobe failed"):
        _get_duration(Path("missing.mp4"))


# --- _cut_track ---


def test_cut_track_stream_copy(monkeypatch):
    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        if kwargs.get("check"):
            return MagicMock()
        return MagicMock(returncode=0)

    monkeypatch.setattr("shorts.cutter.subprocess.run", mock_run)
    monkeypatch.setattr("shorts.cutter._get_duration", lambda p: 10.0)

    _cut_track(Path("in.mp4"), Path("out.mp4"), 5.0, 15.0)
    assert "-c" in calls[0] and "copy" in calls[0]
    assert len(calls) == 1


def test_cut_track_reencode_fallback(monkeypatch):
    calls = []
    duration_calls = [0]

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        if kwargs.get("check"):
            return MagicMock()
        return MagicMock(returncode=0)

    def mock_duration(p):
        duration_calls[0] += 1
        if duration_calls[0] == 1:
            return 12.0
        return 10.0

    monkeypatch.setattr("shorts.cutter.subprocess.run", mock_run)
    monkeypatch.setattr("shorts.cutter._get_duration", mock_duration)

    _cut_track(Path("in.mp4"), Path("out.mp4"), 5.0, 15.0)
    assert len(calls) == 2
    assert "-c:v" in calls[1] and "libx264" in calls[1]


def test_cut_track_ffmpeg_error(monkeypatch):
    def mock_run(cmd, **kwargs):
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(1, cmd, stderr="codec error")
        return MagicMock(returncode=0)

    monkeypatch.setattr("shorts.cutter.subprocess.run", mock_run)
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        _cut_track(Path("in.mp4"), Path("out.mp4"), 0.0, 10.0)


# --- detect_silence ---


def test_detect_silence_no_silence(monkeypatch):
    mock_result = MagicMock()
    mock_result.stderr = "no silence detected"
    monkeypatch.setattr("shorts.cutter.subprocess.run", lambda *a, **kw: mock_result)
    result = detect_silence(Path("test.mp4"))
    assert result == []


def test_detect_silence_with_gaps(monkeypatch):
    stderr = """
silence_start: 2.5
silence_end: 4.2
silence_start: 10.0
silence_end: 11.5
"""
    mock_result = MagicMock()
    mock_result.stderr = stderr
    monkeypatch.setattr("shorts.cutter.subprocess.run", lambda *a, **kw: mock_result)
    result = detect_silence(Path("test.mp4"))
    assert len(result) == 2
    assert result[0] == (2.5, 4.2)
    assert result[1] == (10.0, 11.5)


def test_detect_silence_custom_threshold(monkeypatch):
    mock_result = MagicMock()
    mock_result.stderr = ""
    captured_cmd = []

    def mock_run(cmd, **kwargs):
        captured_cmd.append(cmd)
        return mock_result

    monkeypatch.setattr("shorts.cutter.subprocess.run", mock_run)
    detect_silence(Path("test.mp4"), noise_db=-40.0, min_duration=1.0)
    filter_str = captured_cmd[0][4]
    assert "-40.0dB" in filter_str
    assert "d=1.0" in filter_str


# --- remove_silence ---


def test_remove_silence_no_silent_segments(monkeypatch):
    monkeypatch.setattr("shorts.cutter._get_duration", lambda p: 10.0)
    result = remove_silence(Path("in.mp4"), Path("out.mp4"), [])
    assert result == []


def test_remove_silence_single_keep(monkeypatch):
    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr("shorts.cutter.subprocess.run", mock_run)
    monkeypatch.setattr("shorts.cutter._get_duration", lambda p: 10.0)
    result = remove_silence(Path("in.mp4"), Path("out.mp4"), [(2.0, 5.0)])
    assert len(result) == 2
    assert result[0].orig_start == 0.0
    assert result[0].orig_end == 2.05
    assert result[1].orig_start == 4.95
    assert result[1].orig_end == 10.0


def test_remove_silence_multiple_segments(monkeypatch):
    calls = []

    def mock_run(cmd, **kwargs):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr("shorts.cutter.subprocess.run", mock_run)
    monkeypatch.setattr("shorts.cutter._get_duration", lambda p: 20.0)
    result = remove_silence(Path("in.mp4"), Path("out.mp4"), [(2.0, 5.0), (10.0, 12.0)])
    assert len(result) == 3
    assert result[0].orig_start == 0.0
    assert result[0].orig_end == 2.05
    assert result[1].orig_start == 4.95
    assert result[1].orig_end == 10.05
    assert result[2].orig_start == 11.95
    assert result[2].orig_end == 20.0


# --- cut_clip ---


def test_cut_clip_success(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "ep1.mp4").write_bytes(b"fake")

    working = tmp_path / "working"
    monkeypatch.setattr("shorts.cutter.RAW_DIR", raw)
    monkeypatch.setattr("shorts.cutter.WORKING_DIR", working)

    def mock_cut_track(input_path, output_path, start, end):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"cut")

    monkeypatch.setattr("shorts.cutter._cut_track", mock_cut_track)
    monkeypatch.setattr("shorts.cutter._probe_dimensions", lambda p: (1920, 1080))
    monkeypatch.setattr("shorts.cutter.crop_to_vertical", lambda input, output, **kw: output.write_bytes(b"vertical"))

    clip = Clip(start="01:00", end="01:30", slug="test-clip")
    result = cut_clip("ep1", clip)
    assert result.video_path.exists()
    assert "test-clip_vertical.mp4" in str(result.video_path)
    assert result.kept_segments is None


def test_cut_clip_missing_source(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.cutter.RAW_DIR", tmp_path)
    clip = Clip(start="01:00", end="01:30", slug="test-clip")
    with pytest.raises(FileNotFoundError, match="Missing source"):
        cut_clip("ep1", clip)


def test_cut_clip_with_silence_removal(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "ep1.mp4").write_bytes(b"fake")

    working = tmp_path / "working"
    monkeypatch.setattr("shorts.cutter.RAW_DIR", raw)
    monkeypatch.setattr("shorts.cutter.WORKING_DIR", working)

    def mock_cut_track(input_path, output_path, start, end):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"cut")

    monkeypatch.setattr("shorts.cutter._cut_track", mock_cut_track)
    monkeypatch.setattr("shorts.cutter._probe_dimensions", lambda p: (1920, 1080))
    monkeypatch.setattr("shorts.cutter.detect_silence", lambda p: [(2.0, 5.0)])
    monkeypatch.setattr("shorts.cutter._get_duration", lambda p: 30.0)

    def mock_remove_silence(video, output, segments):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"no silence")
        return [KeptSegment(orig_start=0.0, orig_end=5.05, new_start=0.0)]

    monkeypatch.setattr("shorts.cutter.remove_silence", mock_remove_silence)
    monkeypatch.setattr("shorts.cutter.crop_to_vertical", lambda input, output, **kw: output.write_bytes(b"vertical"))

    clip = Clip(start="01:00", end="01:30", slug="test-clip")
    result = cut_clip("ep1", clip, remove_silence_flag=True)
    assert result.kept_segments is not None
    assert len(result.kept_segments) == 1


# --- CLI integration ---


def test_cli_cut_no_clips(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    result = runner.invoke(app, ["cut", "ep1"])
    assert result.exit_code == 1
    assert "no clips" in result.output.lower()


def test_cli_cut_success(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    clips = [{"start": "01:00", "end": "01:30", "slug": "clip-one"}]
    (tmp_path / "ep1.json").write_text(json.dumps(clips))

    dummy_result = CutResult(video_path=Path("a.mp4"))
    monkeypatch.setattr("shorts.cutter.cut_clip", lambda name, clip, **kw: dummy_result)

    # Mock shutil.copy2 to simulate output
    def mock_copy(src, dst):
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"output")

    monkeypatch.setattr("shutil.copy2", mock_copy)

    result = runner.invoke(app, ["cut", "ep1"])
    assert result.exit_code == 0
    assert "Done:" in result.output
    assert "1/1" in result.output


def test_cli_cut_missing_source(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    clips = [{"start": "01:00", "end": "01:30", "slug": "clip-one"}]
    (tmp_path / "ep1.json").write_text(json.dumps(clips))

    def raise_fnf(name, clip, **kw):
        raise FileNotFoundError("Missing source: raw/ep1.mp4")

    monkeypatch.setattr("shorts.cutter.cut_clip", raise_fnf)

    result = runner.invoke(app, ["cut", "ep1"])
    assert result.exit_code == 1
    assert "Missing source" in result.output


def test_cli_cut_runtime_error_continues(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    clips = [
        {"start": "01:00", "end": "01:30", "slug": "clip-one"},
        {"start": "02:00", "end": "02:30", "slug": "clip-two"},
    ]
    (tmp_path / "ep1.json").write_text(json.dumps(clips))

    call_count = [0]

    def mock_cut(name, clip, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("ffmpeg failed: codec error")
        return CutResult(video_path=Path("a.mp4"))

    monkeypatch.setattr("shorts.cutter.cut_clip", mock_cut)

    def mock_copy(src, dst):
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"output")

    monkeypatch.setattr("shutil.copy2", mock_copy)

    result = runner.invoke(app, ["cut", "ep1"])
    assert result.exit_code == 1
    assert "1/2" in result.output


def test_cli_cut_with_remove_silence(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    clips = [{"start": "01:00", "end": "01:30", "slug": "clip-one"}]
    (tmp_path / "ep1.json").write_text(json.dumps(clips))

    dummy_result = CutResult(video_path=Path("a.mp4"))
    monkeypatch.setattr("shorts.cutter.cut_clip", lambda name, clip, **kw: dummy_result)

    def mock_copy(src, dst):
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"output")

    monkeypatch.setattr("shutil.copy2", mock_copy)

    result = runner.invoke(app, ["cut", "ep1", "--remove-silence"])
    assert result.exit_code == 0
