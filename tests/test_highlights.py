"""Tests for the highlights module."""

import json
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from shorts.cli import app
from shorts.highlights import (
    Clip,
    _format_timestamp,
    load_clips,
    parse_timestamp,
    save_clips,
    suggest_highlights,
    validate_clips,
)
from shorts.transcript import Transcript, TranscriptSegment

runner = CliRunner()

VALID_CLIPS_JSON = json.dumps(
    {
        "clips": [
            {"start": "01:00", "end": "01:45", "slug": "great-moment", "hook": "Amazing intro"},
            {"start": "03:00", "end": "03:40", "slug": "key-insight", "hook": "Big reveal"},
        ]
    }
)


# --- parse_timestamp ---


def test_parse_timestamp_hhmmss():
    assert parse_timestamp("01:30:00") == 5400.0


def test_parse_timestamp_mmss():
    assert parse_timestamp("02:15") == 135.0


def test_parse_timestamp_raw_seconds():
    assert parse_timestamp("45.5") == 45.5


# --- _format_timestamp ---


def test_format_timestamp_zero():
    assert _format_timestamp(0.0) == "00:00"


def test_format_timestamp_minutes():
    assert _format_timestamp(65.5) == "01:05"


def test_format_timestamp_hours():
    assert _format_timestamp(3661.0) == "61:01"


# --- Clip model ---


def test_clip_valid():
    c = Clip(start="01:00", end="01:45", slug="good-slug", hook="A hook")
    assert c.slug == "good-slug"


def test_clip_invalid_slug():
    with pytest.raises(ValueError, match="slug must match"):
        Clip(start="01:00", end="01:45", slug="Bad Slug!")


def test_clip_invalid_slug_suggests_alternative():
    with pytest.raises(ValueError, match="try 'bad-slug' instead"):
        Clip(start="01:00", end="01:45", slug="Bad Slug!")


# --- validate_clips ---


def test_validate_clips_rejects_end_lte_start():
    clips = [Clip(start="02:00", end="01:00", slug="bad-clip")]
    with pytest.raises(ValueError, match="end .* <= start"):
        validate_clips(clips, 300.0)


def test_validate_clips_rejects_end_exceeds_duration():
    clips = [Clip(start="01:00", end="06:00", slug="too-long")]
    with pytest.raises(ValueError, match="exceeds transcript duration"):
        validate_clips(clips, 300.0)


def test_validate_clips_passes_valid():
    clips = [Clip(start="01:00", end="01:45", slug="valid-clip")]
    result = validate_clips(clips, 300.0)
    assert len(result) == 1


def test_validate_clips_warns_outside_range():
    clips = [Clip(start="00:00", end="00:03", slug="short-clip")]
    with pytest.warns(UserWarning, match="outside 5-300s"):
        validate_clips(clips, 300.0)


# --- suggest_highlights ---


def _mock_client(responses):
    """Create a mock httpx.Client that returns given responses in sequence."""
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.post = MagicMock(side_effect=responses)
    return mock


def _ok_response(content):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    resp.text = content
    return resp


def test_suggest_highlights_success(monkeypatch):
    mock = _mock_client([_ok_response(VALID_CLIPS_JSON)])
    monkeypatch.setattr("shorts.highlights.httpx.Client", lambda **kw: mock)
    clips = suggest_highlights("some transcript", "key", "model/x", 2)
    assert len(clips) == 2
    assert clips[0].slug == "great-moment"


def test_suggest_highlights_with_segments(monkeypatch):
    mock = _mock_client([_ok_response(VALID_CLIPS_JSON)])
    monkeypatch.setattr("shorts.highlights.httpx.Client", lambda **kw: mock)

    segments = [
        TranscriptSegment(start=0.0, end=30.0, text="Hello world"),
        TranscriptSegment(start=30.0, end=60.0, text="More text"),
    ]
    clips = suggest_highlights("", "key", "model/x", 2, segments=segments, total_duration=60.0)
    assert len(clips) == 2


def test_suggest_highlights_retries_on_bad_json(monkeypatch):
    bad_resp = _ok_response("not json at all")
    bad_resp.json.return_value = {"choices": [{"message": {"content": "not json at all"}}]}
    good_resp = _ok_response(VALID_CLIPS_JSON)
    mock = _mock_client([bad_resp, good_resp])
    monkeypatch.setattr("shorts.highlights.httpx.Client", lambda **kw: mock)
    monkeypatch.setattr("shorts.highlights.time.sleep", lambda s: None)
    clips = suggest_highlights("text", "key", "model/x", 2)
    assert len(clips) == 2


def test_suggest_highlights_raises_on_second_failure(monkeypatch):
    bad_resp = _ok_response("garbage")
    bad_resp.json.return_value = {"choices": [{"message": {"content": "garbage"}}]}
    mock = _mock_client([bad_resp, bad_resp])
    monkeypatch.setattr("shorts.highlights.httpx.Client", lambda **kw: mock)
    monkeypatch.setattr("shorts.highlights.time.sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="Failed to parse"):
        suggest_highlights("text", "key", "model/x", 2)


def test_suggest_highlights_raises_on_http_error(monkeypatch):
    err_resp = MagicMock()
    err_resp.status_code = 429
    err_resp.text = "rate limited"
    mock = _mock_client([err_resp])
    monkeypatch.setattr("shorts.highlights.httpx.Client", lambda **kw: mock)
    with pytest.raises(RuntimeError, match="429"):
        suggest_highlights("text", "key", "model/x", 2)


# --- save_clips / load_clips ---


def test_save_and_load_clips_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    clips = [Clip(start="01:00", end="01:45", slug="test-clip", hook="Hook")]
    save_clips("ep1", clips)
    loaded = load_clips("ep1")
    assert loaded is not None
    assert loaded[0].slug == "test-clip"


def test_load_clips_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    assert load_clips("nonexistent") is None


# --- CLI integration ---


def test_cli_suggest_success(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    import shorts.config
    from shorts.config import Settings

    monkeypatch.setattr(shorts.config, "settings", Settings(_env_file=None))

    t = Transcript(segments=[TranscriptSegment(start=0, end=300, text="Hello world")])
    (tmp_path / "ep1.json").write_text(t.model_dump_json(indent=2))

    mock = _mock_client([_ok_response(VALID_CLIPS_JSON)])
    monkeypatch.setattr("shorts.highlights.httpx.Client", lambda **kw: mock)

    result = runner.invoke(app, ["suggest", "ep1"])
    assert result.exit_code == 0
    assert "Saved 2 clips" in result.output


def test_cli_suggest_no_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path)
    result = runner.invoke(app, ["suggest", "missing"])
    assert result.exit_code == 1
    assert "no cached transcript" in result.output.lower()
