# Plan: SHORTS-07 Video Cutter (Dual-Track Extraction)

## Summary

Create `src/shorts/cutter.py` that uses ffmpeg subprocess calls to extract matching time segments from both camera and screen video tracks. Camera retains audio (`-c:a copy`), screen strips audio (`-an`). Prefers stream-copy for speed, falls back to re-encode if duration drifts beyond tolerance. Output goes to a working directory for downstream compositing. Wire the existing `cut` CLI stub to iterate over clip specs and call the cutter.

## User Story

As a creator
I want both camera and screen tracks cut at the same timestamps
So that matching segments are ready for compositing

## Metadata

| Field | Value |
|-------|-------|
| Type | NEW_CAPABILITY |
| Complexity | MEDIUM |
| Systems Affected | cutter, cli, tests |
| Jira Issue | SHORTS-07 |

---

## Patterns to Follow

### Directory Constants
```python
# SOURCE: src/shorts/transcript.py:10-11
TRANSCRIPTS_DIR = Path("transcripts")
API_URL = "https://api.supadata.ai/v1/transcript"
```

### Pydantic Models for Data Contracts
```python
# SOURCE: src/shorts/transcript.py:14-16
class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
```

### Error Handling — RuntimeError for External Failures
```python
# SOURCE: src/shorts/transcript.py:36-38
if resp.status_code != 200:
    raise RuntimeError(
        f"Supadata API error {resp.status_code}: {resp.text}. Check your API key."
    )
```

### Error Handling — ValueError for Validation
```python
# SOURCE: src/shorts/highlights.py:49-50
if end <= start:
    raise ValueError(f"Clip '{clip.slug}': end ({clip.end}) <= start ({clip.start})")
```

### CLI Command with Lazy Imports
```python
# SOURCE: src/shorts/cli.py:56-72
@app.command()
def suggest(
    name: str = typer.Argument(..., help="Source name identifier"),
    ...
):
    """AI-suggest clip-worthy highlights from a transcript."""
    from shorts.config import require, settings
    from shorts.highlights import save_clips, suggest_highlights, validate_clips
    from shorts.transcript import load_cached
```

### Tests — Monkeypatch Module Constants
```python
# SOURCE: tests/test_highlights.py:113-116
def test_save_and_load_clips_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    clips = [Clip(start="01:00", end="01:45", slug="test-clip", hook="Hook")]
    save_clips("ep1", clips)
```

### Tests — CLI Integration with CliRunner
```python
# SOURCE: tests/test_highlights.py:124-140
def test_cli_suggest_success(tmp_path, monkeypatch):
    from shorts.transcript import Transcript, TranscriptSegment
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    ...
    result = runner.invoke(app, ["suggest", "ep1"])
    assert result.exit_code == 0
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `src/shorts/cutter.py` | CREATE | Core cutting logic — ffmpeg dual-track extraction |
| `tests/test_cutter.py` | CREATE | Unit tests for cutter module + CLI integration |
| `src/shorts/cli.py` | UPDATE | Wire `cut` command to call cutter |

---

## Tasks

Execute in order. Each task is atomic and verifiable.

### Task 1: Create `src/shorts/cutter.py` with constants and models

- **File**: `src/shorts/cutter.py`
- **Action**: CREATE
- **Implement**:
  - Import `subprocess`, `Path` from pathlib, `BaseModel` from pydantic
  - Define `RAW_DIR = Path("raw")` and `WORKING_DIR = Path("working")`
  - Define `CutResult(BaseModel)` with fields `camera_path: Path` and `screen_path: Path`
  - Define helper `_get_duration(path: Path) -> float` that calls `ffprobe -v error -show_entries format=duration -of csv=p=0 {path}` and returns float seconds. Raises `RuntimeError` if ffprobe fails.
- **Mirror**: `src/shorts/transcript.py:10-16` — Path constants + Pydantic model
- **Validate**: `python -c "from shorts.cutter import RAW_DIR, WORKING_DIR, CutResult"`

### Task 2: Implement `_cut_track` helper

- **File**: `src/shorts/cutter.py`
- **Action**: UPDATE (append)
- **Implement**:
  - Define `_cut_track(input_path: Path, output_path: Path, start: float, end: float, keep_audio: bool) -> None`
  - Build ffmpeg command: `ffmpeg -y -ss {start} -to {end} -i {input_path} -c copy` + (`-c:a copy` if keep_audio else `-an`) + `{output_path}`
  - Run with `subprocess.run(cmd, capture_output=True, text=True, check=True)`
  - After cut, call `_get_duration(output_path)` and compare to expected `(end - start)`. If delta > 0.5s, re-run with `-c:v libx264 -preset fast -crf 18` (and `-c:a aac` if keep_audio) instead of `-c copy`
  - Raise `RuntimeError(f"ffmpeg failed: {e.stderr}")` on `subprocess.CalledProcessError`
- **Mirror**: PRD Risk #1 — keyframe fallback pattern
- **Validate**: `python -c "from shorts.cutter import _cut_track"`

### Task 3: Implement `cut_clip` public function

- **File**: `src/shorts/cutter.py`
- **Action**: UPDATE (append)
- **Implement**:
  - Define `cut_clip(name: str, clip: "Clip") -> CutResult` (import `Clip` and `parse_timestamp` from `shorts.highlights`)
  - Resolve source paths: `RAW_DIR / f"{name}_camera.mp4"` and `RAW_DIR / f"{name}_screen.mp4"`
  - Validate both exist; raise `FileNotFoundError(f"Missing source: {path}")` if not
  - Parse start/end from clip using `parse_timestamp`
  - Create `WORKING_DIR / name` directory (parents=True, exist_ok=True)
  - Define output paths: `working/{name}/{clip.slug}_camera.mp4` and `working/{name}/{clip.slug}_screen.mp4`
  - Call `_cut_track(camera_src, camera_out, start, end, keep_audio=True)`
  - Call `_cut_track(screen_src, screen_out, start, end, keep_audio=False)`
  - Return `CutResult(camera_path=camera_out, screen_path=screen_out)`
- **Mirror**: `src/shorts/highlights.py:87-93` — `load_clips` pattern for file resolution
- **Validate**: `python -c "from shorts.cutter import cut_clip"`

### Task 4: Wire `cut` CLI command

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**:
  - Replace the `cut` command stub body with:
    - Lazy import `from shorts.cutter import cut_clip` and `from shorts.highlights import load_clips`
    - Call `clips = load_clips(name)`; if None, echo error "No clips found" and `raise typer.Exit(1)`
    - Iterate clips with enumerate; for each, `typer.echo(f"Cutting clip {i+1}/{len(clips)}: {clip.slug}")` then call `cut_clip(name, clip)`
    - Wrap each call in try/except: catch `FileNotFoundError` and `RuntimeError`, echo the error, raise `typer.Exit(1)` on `FileNotFoundError` (fatal), continue on `RuntimeError` (per-clip failure)
    - After loop, echo summary: `f"Done: {success}/{len(clips)} clips cut"`
- **Mirror**: `src/shorts/cli.py:56-72` — suggest command pattern with lazy imports and error handling
- **Validate**: `python -m shorts.cli cut --help`

### Task 5: Create `tests/test_cutter.py` — unit tests

- **File**: `tests/test_cutter.py`
- **Action**: CREATE
- **Implement**:
  - Test `_get_duration`: monkeypatch `subprocess.run` to return a mock `CompletedProcess(stdout="45.5\n")`, assert returns 45.5. Also test RuntimeError on non-zero exit.
  - Test `_cut_track` stream-copy path: monkeypatch `subprocess.run` to succeed, monkeypatch `_get_duration` to return expected duration. Assert `subprocess.run` called with `-c copy` args.
  - Test `_cut_track` re-encode fallback: monkeypatch `_get_duration` to return a value >0.5s off on first call (triggering re-encode), then correct on second. Assert second call uses `-c:v libx264`.
  - Test `cut_clip` success: create dummy files in `tmp_path / "raw"`, monkeypatch `RAW_DIR` and `WORKING_DIR`, monkeypatch `_cut_track` to create empty output files. Assert `CutResult` paths exist.
  - Test `cut_clip` missing source: monkeypatch `RAW_DIR` to empty tmp_path. Assert `FileNotFoundError` with expected path in message.
- **Mirror**: `tests/test_transcript.py:42-55` — monkeypatch subprocess mock pattern
- **Validate**: `pytest tests/test_cutter.py -x`

### Task 6: Create `tests/test_cutter.py` — CLI integration tests

- **File**: `tests/test_cutter.py`
- **Action**: UPDATE (append)
- **Implement**:
  - Test CLI `cut` with no clips file: monkeypatch `CLIPS_DIR` to empty tmp_path, invoke `["cut", "ep1"]`, assert exit_code 1 and "no clips" in output.
  - Test CLI `cut` success: monkeypatch `CLIPS_DIR` with a valid clips JSON, monkeypatch `cut_clip` to return a `CutResult` with dummy paths. Assert exit_code 0 and "Done:" in output.
  - Test CLI `cut` with missing source files: monkeypatch `cut_clip` to raise `FileNotFoundError`. Assert exit_code 1.
- **Mirror**: `tests/test_highlights.py:124-148` — CLI test with monkeypatched modules
- **Validate**: `pytest tests/test_cutter.py -x`

---

## Validation

```bash
# Import check
python -c "from shorts.cutter import cut_clip, CutResult, RAW_DIR, WORKING_DIR"

# Tests
pytest tests/test_cutter.py -v

# All tests still pass
pytest

# CLI help
shorts cut --help
```

---

## Acceptance Criteria

- [ ] AC1: Given a clip spec and source files in `raw/`, when cut, then two segment files are produced (camera with audio, screen without audio)
- [ ] AC2: Given the cut segments, when inspected with ffprobe, then durations match the requested range (±0.5s tolerance, re-encode fallback if exceeded)
- [ ] AC3: Given the camera segment, when inspected, then it retains the original audio stream
- [ ] AC4: Given the screen segment, when inspected, then it has no audio stream (`-an`)
- [ ] AC5: Given source files don't exist in `raw/`, when the command runs, then a clear error names the expected file paths
- [ ] All existing tests still pass
- [ ] Follows existing patterns (Path constants, Pydantic models, lazy CLI imports, monkeypatch tests)
