"""Shared fixtures and hooks for the test suite."""

import shutil
import subprocess

import pytest

from shorts.transcript import Transcript, TranscriptSegment


def _ffmpeg_available() -> bool:
    """Check if ffmpeg is on PATH."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests marked @pytest.mark.ffmpeg when ffmpeg is unavailable."""
    if _ffmpeg_available():
        return
    skip = pytest.mark.skip(reason="ffmpeg not available on PATH")
    for item in items:
        if "ffmpeg" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def fixture_video_mp4(tmp_path_factory):
    """Generate a 2-second 320x240 mp4 with sine-wave audio via ffmpeg."""
    path = tmp_path_factory.mktemp("fixtures") / "video.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", "-shortest",
            str(path),
        ],
        capture_output=True,
        check=True,
    )
    return path


@pytest.fixture(scope="session")
def fixture_raw_dir(tmp_path_factory, fixture_video_mp4):
    """Create a raw/ directory with test.mp4."""
    raw = tmp_path_factory.mktemp("raw")
    shutil.copy(fixture_video_mp4, raw / "test.mp4")
    return raw


@pytest.fixture()
def fixture_transcript():
    """Return a Transcript with segments and word-level timestamps spanning 0-2s."""
    return Transcript(
        segments=[TranscriptSegment(start=0.0, end=2.0, text="hello world")],
        words=[
            TranscriptSegment(start=0.0, end=1.0, text="hello"),
            TranscriptSegment(start=1.0, end=2.0, text="world"),
        ],
    )
