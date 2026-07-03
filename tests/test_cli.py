"""Tests for the CLI skeleton."""

from typer.testing import CliRunner

from shorts.cli import app

runner = CliRunner()


def test_help_shows_all_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("download", "transcript", "suggest", "cut", "run", "config"):
        assert cmd in result.output


def test_download_requires_source():
    result = runner.invoke(app, ["download", "ep1"])
    assert result.exit_code != 0  # requires --youtube-url or --local-path


def test_transcript_stub():
    result = runner.invoke(app, ["transcript", "ep1"])
    assert result.exit_code != 0  # requires --youtube-url or --from-file


def test_suggest_requires_transcript():
    result = runner.invoke(app, ["suggest", "ep1"])
    assert result.exit_code == 1
    assert "no cached transcript" in result.output.lower()


def test_cut_no_clips():
    result = runner.invoke(app, ["cut", "ep1"])
    assert result.exit_code == 1
    assert "no clips" in result.output.lower()


def test_run_requires_url_or_cached_transcript(monkeypatch):
    monkeypatch.setattr("shorts.transcript.load_cached", lambda name: None)
    result = runner.invoke(app, ["run", "ep1"])
    assert result.exit_code == 1
    assert "no cached transcript" in result.output.lower()


def test_run_skip_suggest_uses_existing_clips(monkeypatch):
    monkeypatch.setattr(
        "shorts.pipeline.run_pipeline",
        lambda *a, **kw: {"total": 2, "success": 2, "failed": 0, "errors": []},
    )
    result = runner.invoke(app, ["run", "ep1", "--skip-suggest"])
    assert result.exit_code == 0
    assert "2/2" in result.output


def test_run_captions_passes_to_pipeline(monkeypatch):
    captured = {}

    def fake_pipeline(*a, **kw):
        captured.update(kw)
        return {"total": 1, "success": 1, "failed": 0, "errors": []}

    monkeypatch.setattr("shorts.pipeline.run_pipeline", fake_pipeline)
    result = runner.invoke(app, ["run", "ep1", "--skip-suggest", "--captions"])
    assert result.exit_code == 0
    assert captured.get("captions") is True


def test_run_success_end_to_end(monkeypatch):
    monkeypatch.setattr(
        "shorts.pipeline.run_pipeline",
        lambda *a, **kw: {"total": 3, "success": 3, "failed": 0, "errors": []},
    )
    result = runner.invoke(app, ["run", "ep1", "--skip-suggest"])
    assert result.exit_code == 0
    assert "3/3 clips produced" in result.output


def test_config_stub():
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert "DEFAULT_MODEL:" in result.output


def test_run_partial_failure_exits_1(monkeypatch):
    monkeypatch.setattr(
        "shorts.pipeline.run_pipeline",
        lambda *a, **kw: {"total": 3, "success": 2, "failed": 1, "errors": ["clip-x: boom"]},
    )
    result = runner.invoke(app, ["run", "ep1", "--skip-suggest"])
    assert result.exit_code == 1
    assert "FAILED" in result.output


def test_run_fail_fast_passed_to_pipeline(monkeypatch):
    captured = {}

    def fake_pipeline(*a, **kw):
        captured.update(kw)
        return {"total": 1, "success": 1, "failed": 0, "errors": []}

    monkeypatch.setattr("shorts.pipeline.run_pipeline", fake_pipeline)
    runner.invoke(app, ["run", "ep1", "--skip-suggest", "--fail-fast"])
    assert captured.get("fail_fast") is True


def test_cut_partial_failure_exits_1(tmp_path, monkeypatch):
    import json

    from shorts.cutter import CutResult

    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    clips = [{"start": "00:10", "end": "00:40", "slug": "clip-one"}]
    (tmp_path / "ep1.json").write_text(json.dumps(clips))
    monkeypatch.setattr("shorts.cutter.cut_clip", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("fail")))

    result = runner.invoke(app, ["cut", "ep1"])
    assert result.exit_code == 1


def test_cut_captions_requires_transcript(tmp_path, monkeypatch):
    import json

    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    clips = [{"start": "00:10", "end": "00:40", "slug": "clip-one"}]
    (tmp_path / "ep1.json").write_text(json.dumps(clips))
    monkeypatch.setattr("shorts.transcript.load_cached", lambda name: None)

    result = runner.invoke(app, ["cut", "ep1", "--captions"])
    assert result.exit_code == 1
    assert "no cached transcript" in result.output.lower()


def test_cut_captions_success(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from shorts.cutter import CutResult
    from shorts.transcript import Transcript, TranscriptSegment

    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    clips = [{"start": "00:10", "end": "00:40", "slug": "clip-one"}]
    (tmp_path / "ep1.json").write_text(json.dumps(clips))

    transcript = Transcript(segments=[TranscriptSegment(start=10, end=40, text="hi")])
    monkeypatch.setattr("shorts.transcript.load_cached", lambda name: transcript)

    dummy_result = CutResult(video_path=Path("a.mp4"))
    monkeypatch.setattr("shorts.cutter.cut_clip", lambda name, clip, **kw: dummy_result)
    monkeypatch.setattr("shorts.captions.generate_ass", lambda *a, **kw: Path("working/ep1/clip-one.ass"))

    # Mock subprocess.run for subtitle burn-in
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock())

    def mock_copy(src, dst):
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"output")

    monkeypatch.setattr("shutil.copy2", mock_copy)

    from unittest.mock import MagicMock
    result = runner.invoke(app, ["cut", "ep1", "--captions"])
    assert result.exit_code == 0
