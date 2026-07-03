"""Tests for the pipeline orchestration module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shorts.cutter import CutResult
from shorts.highlights import Clip
from shorts.pipeline import run_pipeline
from shorts.transcript import Transcript, TranscriptSegment

FAKE_TRANSCRIPT = Transcript(
    segments=[TranscriptSegment(start=0, end=120, text="hello world")]
)
FAKE_CLIPS = [
    Clip(start="00:10", end="00:40", slug="clip-one"),
    Clip(start="01:00", end="01:30", slug="clip-two"),
]
FAKE_CUT = CutResult(video_path=Path("out_vertical.mp4"))


@patch("shutil.copy2")
@patch("shorts.pipeline.download_youtube")
@patch("shorts.pipeline.cut_clip", return_value=FAKE_CUT)
@patch("shorts.pipeline.load_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_clips")
@patch("shorts.pipeline.validate_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.suggest_highlights", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_transcript")
@patch("shorts.pipeline.fetch_transcript_with_fallback", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.load_cached", return_value=None)
@patch("shorts.pipeline.require", return_value="fake-key")
def test_happy_path(mock_req, mock_load, mock_fetch, mock_save_t, mock_suggest, mock_validate, mock_save_c, mock_load_clips, mock_cut, mock_dl, mock_copy):
    result = run_pipeline("ep1", youtube_url="http://yt.com/v", model="model-x", log=MagicMock())
    assert result == {"total": 2, "success": 2, "failed": 0, "errors": []}
    mock_fetch.assert_called_once()
    mock_suggest.assert_called_once()
    mock_cut.assert_called()
    mock_copy.assert_called()


@patch("shutil.copy2")
@patch("shorts.pipeline.cut_clip", return_value=FAKE_CUT)
@patch("shorts.pipeline.load_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_clips")
@patch("shorts.pipeline.validate_clips")
@patch("shorts.pipeline.suggest_highlights")
@patch("shorts.pipeline.save_transcript")
@patch("shorts.pipeline.fetch_transcript_with_fallback")
@patch("shorts.pipeline.load_cached", return_value=FAKE_TRANSCRIPT)
def test_skip_suggest(mock_load, mock_fetch, mock_save_t, mock_suggest, mock_validate, mock_save_c, mock_load_clips, mock_cut, mock_copy):
    result = run_pipeline("ep1", model="model-x", skip_suggest=True, log=MagicMock())
    assert result["success"] == 2
    mock_fetch.assert_not_called()
    mock_suggest.assert_not_called()


@patch("shutil.copy2")
@patch("shorts.pipeline.download_youtube")
@patch("shorts.pipeline.cut_clip", return_value=FAKE_CUT)
@patch("shorts.pipeline.load_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_clips")
@patch("shorts.pipeline.validate_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.suggest_highlights", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_transcript")
@patch("shorts.pipeline.fetch_transcript_with_fallback", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.load_cached", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.require", return_value="fake-key")
def test_cached_transcript_skips_fetch(mock_req, mock_load, mock_fetch, mock_save_t, mock_suggest, mock_validate, mock_save_c, mock_load_clips, mock_cut, mock_dl, mock_copy):
    run_pipeline("ep1", youtube_url="http://yt.com/v", model="model-x", log=MagicMock())
    mock_fetch.assert_not_called()


@patch("shutil.copy2")
@patch("shorts.pipeline.download_youtube")
@patch("shorts.pipeline.cut_clip")
@patch("shorts.pipeline.load_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_clips")
@patch("shorts.pipeline.validate_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.suggest_highlights", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_transcript")
@patch("shorts.pipeline.fetch_transcript_with_fallback", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.load_cached", return_value=None)
@patch("shorts.pipeline.require", return_value="fake-key")
def test_per_clip_error_continues(mock_req, mock_load, mock_fetch, mock_save_t, mock_suggest, mock_validate, mock_save_c, mock_load_clips, mock_cut, mock_dl, mock_copy):
    mock_cut.side_effect = [RuntimeError("ffmpeg fail"), FAKE_CUT]
    result = run_pipeline("ep1", youtube_url="http://yt.com/v", model="model-x", log=MagicMock())
    assert result == {"total": 2, "success": 1, "failed": 1, "errors": ["clip-one: ffmpeg fail"]}


@patch("shorts.pipeline.load_cached", return_value=None)
def test_no_url_no_cache_raises(mock_load):
    with pytest.raises(RuntimeError, match="Video not found"):
        run_pipeline("ep1", model="model-x", log=MagicMock())


@patch("shutil.copy2")
@patch("shorts.pipeline.download_youtube")
@patch("shorts.pipeline.cut_clip")
@patch("shorts.pipeline.load_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_clips")
@patch("shorts.pipeline.validate_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.suggest_highlights", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_transcript")
@patch("shorts.pipeline.fetch_transcript_with_fallback", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.load_cached", return_value=None)
@patch("shorts.pipeline.require", return_value="fake-key")
def test_file_not_found_propagates(mock_req, mock_load, mock_fetch, mock_save_t, mock_suggest, mock_validate, mock_save_c, mock_load_clips, mock_cut, mock_dl, mock_copy):
    mock_cut.side_effect = FileNotFoundError("Missing source: raw/ep1.mp4")
    with pytest.raises(FileNotFoundError):
        run_pipeline("ep1", youtube_url="http://yt.com/v", model="model-x", log=MagicMock())



@patch("shutil.copy2")
@patch("shorts.pipeline.download_youtube")
@patch("shorts.pipeline.cut_clip")
@patch("shorts.pipeline.load_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_clips")
@patch("shorts.pipeline.validate_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.suggest_highlights", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_transcript")
@patch("shorts.pipeline.fetch_transcript_with_fallback", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.load_cached", return_value=None)
@patch("shorts.pipeline.require", return_value="fake-key")
def test_fail_fast_stops_on_first_error(mock_req, mock_load, mock_fetch, mock_save_t, mock_suggest, mock_validate, mock_save_c, mock_load_clips, mock_cut, mock_dl, mock_copy):
    mock_cut.side_effect = [RuntimeError("fail"), FAKE_CUT]
    result = run_pipeline("ep1", youtube_url="http://yt.com/v", model="model-x", fail_fast=True, log=MagicMock())
    assert result["success"] == 0
    assert result["failed"] == 1
    assert result["errors"] == ["clip-one: fail"]
    mock_copy.assert_not_called()


@patch("shutil.copy2")
@patch("shorts.pipeline.download_youtube")
@patch("shorts.pipeline.cut_clip", return_value=FAKE_CUT)
@patch("shorts.pipeline.load_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_clips")
@patch("shorts.pipeline.validate_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.suggest_highlights", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_transcript")
@patch("shorts.pipeline.fetch_transcript_with_fallback", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.load_cached", return_value=None)
@patch("shorts.pipeline.require", return_value="fake-key")
def test_captions_true_calls_generate_ass(mock_req, mock_load, mock_fetch, mock_save_t, mock_suggest, mock_validate, mock_save_c, mock_load_clips, mock_cut, mock_dl, mock_copy):
    with patch("shorts.pipeline.generate_ass", return_value=Path("working/ep1/clip-one.ass")) as mock_gen:
        run_pipeline("ep1", youtube_url="http://yt.com/v", model="model-x", captions=True, log=MagicMock())
        mock_gen.assert_called()


@patch("shutil.copy2")
@patch("shorts.pipeline.download_youtube")
@patch("shorts.pipeline.cut_clip", return_value=FAKE_CUT)
@patch("shorts.pipeline.load_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_clips")
@patch("shorts.pipeline.validate_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.suggest_highlights", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_transcript")
@patch("shorts.pipeline.fetch_transcript_with_fallback", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.load_cached", return_value=None)
@patch("shorts.pipeline.require", return_value="fake-key")
def test_captions_false_skips_generate_ass(mock_req, mock_load, mock_fetch, mock_save_t, mock_suggest, mock_validate, mock_save_c, mock_load_clips, mock_cut, mock_dl, mock_copy):
    with patch("shorts.pipeline.generate_ass") as mock_gen:
        run_pipeline("ep1", youtube_url="http://yt.com/v", model="model-x", captions=False, log=MagicMock())
        mock_gen.assert_not_called()
