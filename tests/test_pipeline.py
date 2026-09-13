"""Tests for the pipeline orchestration module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shorts.cutter import CutResult
from shorts.highlights import Clip
from shorts.pipeline import run_pipeline, step_cut, step_download, step_suggest, step_transcript
from shorts.transcript import Transcript, TranscriptSegment

FAKE_TRANSCRIPT = Transcript(
    segments=[TranscriptSegment(start=0, end=120, text="hello world")]
)
FAKE_CLIPS = [
    Clip(start="00:10", end="00:40", slug="clip-one"),
    Clip(start="01:00", end="01:30", slug="clip-two"),
]
FAKE_CUT = CutResult(video_path=Path("out_vertical.mp4"))


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Run in a scratch dir so cached artifacts in the repo (raw/, output/) can't interfere."""
    monkeypatch.chdir(tmp_path)


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
        run_pipeline(
            "ep1", youtube_url="http://yt.com/v", model="model-x",
            captions=False, crop={"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8},
            log=MagicMock()
        )
        mock_gen.assert_not_called()


@patch("shorts.pipeline.download_youtube")
def test_step_download_skips_existing_video(mock_dl):
    Path("raw").mkdir()
    (Path("raw") / "ep1.mp4").write_bytes(b"x")
    step_download("ep1", youtube_url="http://yt.com/v", log=MagicMock())
    mock_dl.assert_not_called()


@patch("shorts.pipeline.download_youtube")
def test_step_download_force_redownloads(mock_dl):
    Path("raw").mkdir()
    (Path("raw") / "ep1.mp4").write_bytes(b"x")
    step_download("ep1", youtube_url="http://yt.com/v", force=True, log=MagicMock())
    mock_dl.assert_called_once()


@patch("shorts.pipeline.fetch_transcript_with_fallback", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.save_transcript")
@patch("shorts.pipeline.load_cached", return_value=FAKE_TRANSCRIPT)
def test_step_transcript_uses_cache(mock_load, mock_save_t, mock_fetch):
    result = step_transcript("ep1", youtube_url="http://yt.com/v", log=MagicMock())
    assert result == FAKE_TRANSCRIPT
    mock_fetch.assert_not_called()


@patch("shorts.pipeline.fetch_transcript_with_fallback", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.save_transcript")
@patch("shorts.pipeline.load_cached", return_value=FAKE_TRANSCRIPT)
def test_step_transcript_force_refetches(mock_load, mock_save_t, mock_fetch):
    step_transcript("ep1", youtube_url="http://yt.com/v", force=True, log=MagicMock())
    mock_fetch.assert_called_once()


@patch("shorts.pipeline.save_clips")
@patch("shorts.pipeline.validate_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.suggest_highlights", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.load_cached", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.require", return_value="fake-key")
def test_step_suggest_reuses_existing_clips(mock_req, mock_load, mock_suggest, mock_validate, mock_save_c):
    import json
    Path("clips").mkdir()
    (Path("clips") / "ep1.json").write_text(json.dumps([
        {"start": "00:10", "end": "00:40", "slug": "clip-one"}
    ]))
    clips = step_suggest("ep1", model="model-x", log=MagicMock())
    assert len(clips) == 1
    mock_suggest.assert_not_called()


@patch("shutil.copy2")
@patch("shorts.pipeline.cut_clip", return_value=FAKE_CUT)
@patch("shorts.pipeline.load_clips", return_value=FAKE_CLIPS)
def test_step_cut_resume_skips_existing_outputs(mock_load_clips, mock_cut, mock_copy):
    out_dir = Path("output") / "ep1"
    out_dir.mkdir(parents=True)
    (out_dir / "ep1_short_01_clip-one.mp4").write_bytes(b"x")

    result = step_cut("ep1", log=MagicMock())

    assert result == {"total": 2, "success": 2, "failed": 0, "errors": []}
    assert mock_cut.call_count == 1  # only clip-two was rendered
    mock_copy.assert_called_once()


@patch("shutil.copy2")
@patch("shorts.pipeline.cut_clip", return_value=FAKE_CUT)
@patch("shorts.pipeline.load_clips", return_value=FAKE_CLIPS)
def test_step_cut_resume_false_rerenders_all(mock_load_clips, mock_cut, mock_copy):
    out_dir = Path("output") / "ep1"
    out_dir.mkdir(parents=True)
    (out_dir / "ep1_short_01_clip-one.mp4").write_bytes(b"x")

    result = step_cut("ep1", resume=False, log=MagicMock())

    assert result["success"] == 2
    assert mock_cut.call_count == 2


@patch("shorts.pipeline.load_clips", return_value=None)
def test_step_cut_no_clips_raises(mock_load_clips):
    with pytest.raises(RuntimeError, match="No clips found"):
        step_cut("ep1", log=MagicMock())


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
def test_run_pipeline_force_bypasses_all_caches(mock_req, mock_load, mock_fetch, mock_save_t, mock_suggest, mock_validate, mock_save_c, mock_load_clips, mock_cut, mock_dl, mock_copy):
    Path("raw").mkdir()
    (Path("raw") / "ep1.mp4").write_bytes(b"x")
    Path("clips").mkdir()
    (Path("clips") / "ep1.json").write_text('[{"start": "00:10", "end": "00:40", "slug": "clip-one"}]')

    result = run_pipeline("ep1", youtube_url="http://yt.com/v", model="model-x", force=True, log=MagicMock())

    assert result["success"] == 2
    mock_dl.assert_called_once()      # existing raw video ignored
    mock_suggest.assert_called_once()  # existing clips ignored
    assert mock_cut.call_count == 2    # no resume skips
