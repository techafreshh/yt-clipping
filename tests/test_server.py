"""Tests for the server module."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from shorts.server import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.server.RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path / "clips")
    (tmp_path / "raw").mkdir()
    (tmp_path / "clips").mkdir()
    app = create_app()
    return TestClient(app)


@pytest.fixture
def video_file(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    vid = raw / "ep1.mp4"
    vid.write_bytes(b"\x00" * 1024)
    return vid


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_video_serve_missing(client):
    resp = client.get("/api/videos/nonexistent")
    assert resp.status_code == 404


def test_video_serve_range(client, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    vid = raw / "ep1.mp4"
    vid.write_bytes(b"A" * 1000)

    resp = client.get("/api/videos/ep1", headers={"Range": "bytes=0-99"})
    assert resp.status_code == 206
    assert resp.headers["content-range"] == "bytes 0-99/1000"
    assert len(resp.content) == 100


def test_video_serve_full(client, tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    vid = raw / "ep1.mp4"
    vid.write_bytes(b"B" * 500)

    resp = client.get("/api/videos/ep1")
    assert resp.status_code == 200
    assert len(resp.content) == 500


def test_clips_crud(client, tmp_path):
    # GET empty
    resp = client.get("/api/clips/ep1")
    assert resp.status_code == 200
    assert resp.json() == []

    # POST create
    clip = {"start": "01:00", "end": "01:30", "slug": "test-clip"}
    resp = client.post("/api/clips/ep1", json=clip)
    assert resp.status_code == 201
    assert resp.json()["slug"] == "test-clip"

    # GET after create
    resp = client.get("/api/clips/ep1")
    assert len(resp.json()) == 1

    # PUT update
    updated = {"start": "01:00", "end": "02:00", "slug": "test-clip", "hook": "updated"}
    resp = client.put("/api/clips/ep1/0", json=updated)
    assert resp.status_code == 200
    assert resp.json()["hook"] == "updated"

    # DELETE
    resp = client.delete("/api/clips/ep1/0")
    assert resp.status_code == 200
    resp = client.get("/api/clips/ep1")
    assert resp.json() == []


def test_clips_with_crop(client):
    clip = {
        "start": "01:00", "end": "01:30", "slug": "crop-test",
        "crop": {"x": 0.1, "y": 0.2, "w": 0.8, "h": 0.6},
    }
    resp = client.post("/api/clips/ep1", json=clip)
    assert resp.status_code == 201

    resp = client.get("/api/clips/ep1")
    data = resp.json()[0]
    assert data["crop"] == {"x": 0.1, "y": 0.2, "w": 0.8, "h": 0.6}


def test_clips_index_out_of_range(client):
    resp = client.put("/api/clips/ep1/99", json={"start": "01:00", "end": "01:30", "slug": "x"})
    assert resp.status_code == 404

    resp = client.delete("/api/clips/ep1/99")
    assert resp.status_code == 404


def test_cut_endpoint_no_clips(client):
    resp = client.get("/api/cut/ep1")
    assert resp.status_code == 404


def test_cut_endpoint_sse(client, tmp_path, monkeypatch):
    # Create a clip
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir(exist_ok=True)
    clips_data = [{"start": "01:00", "end": "01:30", "slug": "sse-test"}]
    (clips_dir / "ep1.json").write_text(json.dumps(clips_data))

    # Mock cut_clip at its source module
    mock_cut_result = MagicMock()
    mock_cut_result.video_path = Path("out.mp4")

    with patch("shorts.cutter.cut_clip", return_value=mock_cut_result):
        with patch("shutil.copy2"):
            resp = client.get("/api/cut/ep1")
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            lines = [l for l in resp.text.split("\n") if l.startswith("data:")]
            assert len(lines) >= 2  # at least cutting + done/complete
            # Check final event
            last = json.loads(lines[-1].replace("data: ", ""))
            assert last["status"] == "complete"


def test_download_endpoint_youtube(client, monkeypatch):
    with patch("shorts.downloader.download_youtube") as mock_dl:
        resp = client.post("/api/download", json={"name": "test", "youtube_url": "https://youtube.com/watch?v=abc"})
        assert resp.status_code == 200
        mock_dl.assert_called_once_with("https://youtube.com/watch?v=abc", "test")


def test_download_endpoint_local(client, monkeypatch):
    with patch("shorts.downloader.load_local_video") as mock_load:
        resp = client.post("/api/download", json={"name": "test", "local_path": "/path/to/video.mp4"})
        assert resp.status_code == 200
        mock_load.assert_called_once()


def test_download_requires_source(client):
    resp = client.post("/api/download", json={"name": "test"})
    assert resp.status_code == 400


def test_auto_transcript(client, monkeypatch):
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", Path("/nonexistent"))
    monkeypatch.setattr("shorts.server.RAW_DIR", Path("/nonexistent"))

    with patch("shorts.transcript.fetch_transcript_with_fallback") as mock_fetch:
        mock_transcript = MagicMock()
        mock_transcript.segments = [MagicMock()]
        mock_fetch.return_value = mock_transcript
        with patch("shorts.transcript.save_transcript"):
            resp = client.post("/api/auto/transcript", json={"name": "test", "youtube_url": "https://yt.com/v"})
            assert resp.status_code == 200


def test_auto_suggest(client, tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path / "clips")
    (tmp_path / "clips").mkdir(exist_ok=True)

    with patch("shorts.transcript.load_cached") as mock_cached:
        mock_transcript = MagicMock()
        mock_transcript.segments = [MagicMock(end=100.0)]
        mock_cached.return_value = mock_transcript
        with patch("shorts.config.require", return_value="fake-key"):
            with patch("shorts.highlights.suggest_highlights") as mock_suggest:
                mock_suggest.return_value = []
                with patch("shorts.highlights.save_clips"):
                    resp = client.post("/api/auto/suggest", json={"name": "test", "count": 3})
                    assert resp.status_code == 200
