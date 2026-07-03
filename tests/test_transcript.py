"""Tests for the transcript module."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from shorts.cli import app
from shorts.transcript import (
    Transcript,
    TranscriptSegment,
    fetch_transcript,
    fetch_transcript_with_fallback,
    fetch_transcript_ytdlp,
    load_cached,
    load_from_file,
    save_transcript,
)

runner = CliRunner()

SAMPLE_SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "Hello world"},
    {"start": 2.5, "end": 5.0, "text": "Second segment"},
]


def test_transcript_model_valid():
    t = Transcript(segments=[TranscriptSegment(start=0, end=1, text="hi")])
    assert t.segments[0].text == "hi"
    assert t.segments[0].start == 0.0


def test_transcript_model_optional_words():
    t = Transcript(segments=[TranscriptSegment(start=0, end=1, text="hi")])
    assert t.words is None


def test_save_and_load_cached(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path)
    t = Transcript(segments=[TranscriptSegment(start=0, end=1, text="cached")])
    save_transcript("test1", t)
    loaded = load_cached("test1")
    assert loaded is not None
    assert loaded.segments[0].text == "cached"


def test_load_cached_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path)
    assert load_cached("nonexistent") is None


def test_fetch_transcript_success(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"content": SAMPLE_SEGMENTS}

    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp

    monkeypatch.setattr("shorts.transcript.httpx.Client", lambda **kw: mock_client)
    result = fetch_transcript("https://youtube.com/watch?v=abc", "sk-key")
    assert len(result.segments) == 2
    assert result.segments[0].text == "Hello world"


def test_fetch_transcript_retries_on_5xx(monkeypatch):
    fail_resp = MagicMock()
    fail_resp.status_code = 500

    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"content": SAMPLE_SEGMENTS}

    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = [fail_resp, ok_resp]

    monkeypatch.setattr("shorts.transcript.httpx.Client", lambda **kw: mock_client)
    monkeypatch.setattr("shorts.transcript.time.sleep", lambda s: None)
    result = fetch_transcript("https://youtube.com/watch?v=abc", "sk-key")
    assert len(result.segments) == 2


def test_fetch_transcript_error_on_4xx(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp

    monkeypatch.setattr("shorts.transcript.httpx.Client", lambda **kw: mock_client)
    with pytest.raises(RuntimeError, match="401"):
        fetch_transcript("https://youtube.com/watch?v=abc", "sk-bad")


def test_cli_transcript_fetches_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setenv("SUPADATA_API_KEY", "sk-test")

    import shorts.config
    from shorts.config import Settings

    monkeypatch.setattr(shorts.config, "settings", Settings(_env_file=None))

    t = Transcript(segments=[TranscriptSegment(start=0, end=1, text="hi")])
    monkeypatch.setattr("shorts.transcript.fetch_transcript", lambda url, key: t)

    result = runner.invoke(app, ["transcript", "vid1", "--youtube-url", "https://youtube.com/watch?v=x"])
    assert result.exit_code == 0
    assert (tmp_path / "vid1.json").exists()


def test_cli_transcript_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path)
    t = Transcript(segments=[TranscriptSegment(start=0, end=1, text="cached")])
    (tmp_path / "vid1.json").write_text(t.model_dump_json(indent=2))

    result = runner.invoke(app, ["transcript", "vid1", "--youtube-url", "https://youtube.com/watch?v=x"])
    assert result.exit_code == 0
    assert "Using cached transcript" in result.output


def test_cli_transcript_force_refetches(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setenv("SUPADATA_API_KEY", "sk-test")

    import shorts.config
    from shorts.config import Settings

    monkeypatch.setattr(shorts.config, "settings", Settings(_env_file=None))

    old = Transcript(segments=[TranscriptSegment(start=0, end=1, text="old")])
    (tmp_path / "vid1.json").write_text(old.model_dump_json(indent=2))

    new = Transcript(segments=[TranscriptSegment(start=0, end=2, text="new")])
    monkeypatch.setattr("shorts.transcript.fetch_transcript", lambda url, key: new)

    result = runner.invoke(app, ["transcript", "vid1", "--youtube-url", "https://youtube.com/watch?v=x", "--force"])
    assert result.exit_code == 0
    loaded = json.loads((tmp_path / "vid1.json").read_text())
    assert loaded["segments"][0]["text"] == "new"


def test_cli_transcript_no_source():
    result = runner.invoke(app, ["transcript", "vid1"])
    assert result.exit_code != 0
    assert "youtube" in result.output and "from" in result.output


def test_load_from_file_json(tmp_path):
    t = Transcript(segments=[TranscriptSegment(start=1.0, end=2.0, text="hello")])
    f = tmp_path / "input.json"
    f.write_text(t.model_dump_json())
    loaded = load_from_file(f)
    assert loaded.segments[0].text == "hello"
    assert loaded.segments[0].start == 1.0


def test_load_from_file_txt(tmp_path):
    f = tmp_path / "input.txt"
    f.write_text("Some transcript text")
    with pytest.warns(UserWarning, match="approximate"):
        loaded = load_from_file(f)
    assert len(loaded.segments) == 1
    assert loaded.segments[0].text == "Some transcript text"
    assert loaded.segments[0].start == 0.0
    assert loaded.segments[0].end == 0.0


def test_load_from_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_from_file(tmp_path / "missing.json")


def test_cli_transcript_from_file_json(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", out_dir)
    t = Transcript(segments=[TranscriptSegment(start=0, end=1, text="from file")])
    f = tmp_path / "input.json"
    f.write_text(t.model_dump_json())
    result = runner.invoke(app, ["transcript", "vid1", "--from-file", str(f)])
    assert result.exit_code == 0
    assert (out_dir / "vid1.json").exists()


def test_cli_transcript_from_file_txt(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", out_dir)
    f = tmp_path / "input.txt"
    f.write_text("plain text transcript")
    result = runner.invoke(app, ["transcript", "vid1", "--from-file", str(f)])
    assert result.exit_code == 0
    assert (out_dir / "vid1.json").exists()


def test_cli_transcript_from_file_not_found():
    result = runner.invoke(app, ["transcript", "vid1", "--from-file", "nonexistent.json"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_cli_transcript_both_options():
    result = runner.invoke(app, ["transcript", "vid1", "--youtube-url", "http://x", "--from-file", "f.json"])
    assert result.exit_code != 0
    assert "only one" in result.output.lower()


# --- fetch_transcript_with_fallback ---


def test_fallback_uses_supadata_first(monkeypatch):
    t = Transcript(segments=[TranscriptSegment(start=0, end=1, text="supadata")])
    monkeypatch.setattr("shorts.transcript.fetch_transcript", lambda url, key: t)

    result = fetch_transcript_with_fallback("https://yt.com/v", "test", api_key="sk-key")
    assert result.segments[0].text == "supadata"


def test_fallback_uses_ytdlp_when_supadata_fails(monkeypatch):
    def raise_error(url, key):
        raise RuntimeError("Supadata failed")

    monkeypatch.setattr("shorts.transcript.fetch_transcript", raise_error)

    t = Transcript(segments=[TranscriptSegment(start=0, end=1, text="ytdlp")])
    monkeypatch.setattr("shorts.transcript.fetch_transcript_ytdlp", lambda url, name: t)

    result = fetch_transcript_with_fallback("https://yt.com/v", "test", api_key="sk-key")
    assert result.segments[0].text == "ytdlp"


def test_fallback_no_api_key_uses_ytdlp(monkeypatch):
    t = Transcript(segments=[TranscriptSegment(start=0, end=1, text="ytdlp")])
    monkeypatch.setattr("shorts.transcript.fetch_transcript_ytdlp", lambda url, name: t)

    result = fetch_transcript_with_fallback("https://yt.com/v", "test", api_key=None)
    assert result.segments[0].text == "ytdlp"


# --- fetch_transcript_ytdlp ---


def test_fetch_transcript_ytdlp_success(monkeypatch, tmp_path):
    import json

    json3_data = {
        "events": [
            {"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "Hello"}]},
            {"tStartMs": 1000, "dDurationMs": 1000, "segs": [{"utf8": " world"}]},
        ]
    }

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        # Write the json3 file
        out_dir = Path(cmd[cmd.index("-o") + 1]).parent
        json3_path = out_dir / "test.en.json3"
        json3_path.write_text(json.dumps(json3_data))
        return result

    monkeypatch.setattr("shorts.transcript.subprocess.run", mock_run)
    result = fetch_transcript_ytdlp("https://yt.com/v", "test")
    assert len(result.segments) == 2
    assert result.segments[0].text == "Hello"
    assert result.segments[1].text == "world"


def test_fetch_transcript_ytdlp_no_subtitles(monkeypatch):
    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr("shorts.transcript.subprocess.run", mock_run)
    with pytest.raises(RuntimeError, match="No subtitles found"):
        fetch_transcript_ytdlp("https://yt.com/v", "test")


def test_fetch_transcript_ytdlp_ytdlp_not_found(monkeypatch):
    def mock_run(cmd, **kwargs):
        raise FileNotFoundError("not found")

    monkeypatch.setattr("shorts.transcript.subprocess.run", mock_run)
    with pytest.raises(RuntimeError, match="yt-dlp not found"):
        fetch_transcript_ytdlp("https://yt.com/v", "test")
