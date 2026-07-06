"""Tests for the downloader module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shorts.downloader import extract_audio, get_video_duration, get_video_dimensions, load_local_video, RAW_DIR


def test_load_local_video_copies_file(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.downloader.RAW_DIR", tmp_path)
    src = tmp_path / "source.mp4"
    src.write_bytes(b"video data")

    result = load_local_video(src, "test")
    assert result.exists()
    assert result == tmp_path / "test.mp4"
    assert result.read_bytes() == b"video data"


def test_load_local_video_already_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.downloader.RAW_DIR", tmp_path)
    dest = tmp_path / "test.mp4"
    dest.write_bytes(b"existing")

    result = load_local_video(dest, "test")
    assert result == dest
    assert result.read_bytes() == b"existing"


def test_extract_audio_success(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.downloader.RAW_DIR", tmp_path)
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake video")

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        # Create the output file so it "exists"
        output_path = Path(cmd[-1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"audio data")
        return result

    monkeypatch.setattr("shorts.downloader.subprocess.run", mock_run)
    result = extract_audio(video, "test")
    assert result.exists()
    assert "_audio.wav" in str(result)


def test_extract_audio_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.downloader.RAW_DIR", tmp_path)
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake video")

    def mock_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="ffmpeg error")

    monkeypatch.setattr("shorts.downloader.subprocess.run", mock_run)
    with pytest.raises(RuntimeError, match="Audio extraction failed"):
        extract_audio(video, "test")


def test_get_video_duration(tmp_path, monkeypatch):
    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "120.5\n"
        return result

    monkeypatch.setattr("shorts.downloader.subprocess.run", mock_run)
    assert get_video_duration(Path("test.mp4")) == 120.5


def test_get_video_dimensions(tmp_path, monkeypatch):
    import json

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = json.dumps({"streams": [{"width": 1920, "height": 1080}]})
        return result

    monkeypatch.setattr("shorts.downloader.subprocess.run", mock_run)
    w, h = get_video_dimensions(Path("test.mp4"))
    assert w == 1920
    assert h == 1080


def test_download_youtube_success(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.downloader.RAW_DIR", tmp_path)

    def mock_savenow(url, dest):
        raise Exception("savenow failed")
    monkeypatch.setattr("shorts.downloader._download_via_savenow", mock_savenow)

    class MockProcess:
        def __init__(self):
            self.stdout = ["[download] 100%"]
            self.returncode = 0
        def wait(self):
            output = tmp_path / "test.mp4"
            output.write_bytes(b"downloaded")
            return 0

    monkeypatch.setattr("shorts.downloader.subprocess.Popen", lambda *args, **kwargs: MockProcess())

    from shorts.downloader import download_youtube
    result = download_youtube("https://youtube.com/watch?v=abc", "test")
    assert result.exists()


def test_download_youtube_ytdlp_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.downloader.RAW_DIR", tmp_path)

    def mock_savenow(url, dest):
        raise Exception("savenow failed")
    monkeypatch.setattr("shorts.downloader._download_via_savenow", mock_savenow)

    def mock_popen(*args, **kwargs):
        raise FileNotFoundError("yt-dlp not found")
    monkeypatch.setattr("shorts.downloader.subprocess.Popen", mock_popen)

    from shorts.downloader import download_youtube
    with pytest.raises(RuntimeError, match="yt-dlp not found"):
        download_youtube("https://youtube.com/watch?v=abc", "test")
