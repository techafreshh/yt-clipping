# Plan: SHORTS-12 TikTok-Style Captions

## Summary

Create `src/shorts/captions.py` that generates ASS subtitle files from transcript word/segment timestamps, then integrate into the compositor's ffmpeg filter chain via the `subtitles` filter. Captions use bold white text with black stroke, word-by-word highlight style. The `--captions` flag on `cut` and `run` commands triggers caption burn-in. Falls back to segment-level timing when word timestamps are unavailable.

## User Story

As a creator
I want optional TikTok-style captions burned into my shorts
So that I can improve retention without using a separate captioning tool

## Metadata

| Field | Value |
|-------|-------|
| Type | NEW_CAPABILITY |
| Complexity | MEDIUM |
| Systems Affected | captions (new), compositor, pipeline, cli, tests |
| Jira Issue | SHORTS-12 |

---

## Patterns to Follow

### Directory Constants & Module Structure
```python
# SOURCE: src/shorts/cutter.py:1-9
import subprocess
from pathlib import Path

from pydantic import BaseModel

RAW_DIR = Path("raw")
WORKING_DIR = Path("working")
```

### Subprocess ffmpeg with CalledProcessError → RuntimeError
```python
# SOURCE: src/shorts/compositor.py:38-44
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Compositing failed: {e.stderr}")
```

### Compositor filter_complex chain
```python
# SOURCE: src/shorts/compositor.py:17-24
    filter_complex = (
        f"[0:v]scale={WIDTH}:{top_h}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{top_h}:(ow-iw)/2:(oh-ih)/2[top];"
        f"[1:v]scale={WIDTH}:{bot_h}:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{bot_h}:(ow-iw)/2:(oh-ih)/2[bot];"
        f"[top][bot]vstack=inputs=2[v]"
    )
```

### Transcript model with optional words
```python
# SOURCE: src/shorts/transcript.py:20-24
class Transcript(BaseModel):
    segments: list[TranscriptSegment]
    words: Optional[list[TranscriptSegment]] = None
```

### CLI lazy imports and option wiring
```python
# SOURCE: src/shorts/cli.py:86-92
    from shorts.compositor import composite_clip
    from shorts.config import settings
    from shorts.cutter import cut_clip
    from shorts.highlights import load_clips
```

### Tests — monkeypatch subprocess + tmp_path
```python
# SOURCE: tests/test_compositor.py:18-27
def test_composite_clip_success(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.compositor.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        "shorts.compositor.subprocess.run", lambda *a, **kw: MagicMock()
    )

    clip = Clip(start="01:00", end="01:30", slug="test-clip")
    cut_result = CutResult(camera_path=Path("cam.mp4"), screen_path=Path("scr.mp4"))

    result = composite_clip("ep1", clip, cut_result, 1)
    assert result == tmp_path / "ep1" / "ep1_short_01_test-clip.mp4"
```

### Pipeline — patch-based tests
```python
# SOURCE: tests/test_pipeline.py:28-37
@patch("shorts.pipeline.composite_clip", return_value=Path("out.mp4"))
@patch("shorts.pipeline.cut_clip", return_value=FAKE_CUT)
@patch("shorts.pipeline.load_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_clips")
@patch("shorts.pipeline.validate_clips", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.suggest_highlights", return_value=FAKE_CLIPS)
@patch("shorts.pipeline.save_transcript")
@patch("shorts.pipeline.fetch_transcript", return_value=FAKE_TRANSCRIPT)
@patch("shorts.pipeline.load_cached", return_value=None)
@patch("shorts.pipeline.require", return_value="fake-key")
def test_happy_path(mock_req, mock_load, ...):
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `src/shorts/captions.py` | CREATE | ASS subtitle generation from transcript timestamps |
| `src/shorts/compositor.py` | UPDATE | Add optional `subtitle_path` param, insert subtitles filter into chain |
| `src/shorts/pipeline.py` | UPDATE | Accept `captions` param, load transcript, call captions generator, pass to compositor |
| `src/shorts/cli.py` | UPDATE | Add `--captions` to `cut`, remove "not yet implemented" warning from `run`, pass captions+transcript through |
| `tests/test_captions.py` | CREATE | Unit tests for ASS generation logic |
| `tests/test_compositor.py` | UPDATE | Tests for compositor with subtitle_path |
| `tests/test_pipeline.py` | UPDATE | Tests for pipeline with captions=True |
| `tests/test_cli.py` | UPDATE | Update `run --captions` test, add `cut --captions` test |

---

## Tasks

Execute in order. Each task is atomic and verifiable.

### Task 1: Create `src/shorts/captions.py` — ASS subtitle generation

- **File**: `src/shorts/captions.py`
- **Action**: CREATE
- **Implement**:
  - Import `Path` from pathlib
  - Define `WORKING_DIR = Path("working")`
  - Define helper `_format_ass_time(seconds: float) -> str` that converts float seconds to ASS time format `H:MM:SS.cc` (centiseconds)
  - Define `generate_ass(name: str, slug: str, transcript, clip_start: float, clip_end: float) -> Path`:
    - Accept transcript (Transcript model from `shorts.transcript`)
    - Determine word list: use `transcript.words` if available, else fall back to `transcript.segments`
    - Filter words/segments to those overlapping the clip window `[clip_start, clip_end]`
    - Offset all timestamps by subtracting `clip_start` (so captions start at 0:00 relative to clip)
    - Build ASS file content:
      - Header with `[Script Info]`, `PlayResX: 1080`, `PlayResY: 1920`
      - `[V4+ Styles]` section with a single style: `Style: Default,Arial,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,0,2,10,10,50,1`
        - Bold (field 8 = 1), white primary (&H00FFFFFF), black outline (&H00000000), outline width 4, alignment 2 (bottom-center)
      - `[Events]` section with `Dialogue` lines for each word/segment
      - For word-level: each word gets its own Dialogue line with exact start/end times
      - For segment-level fallback: each segment gets a Dialogue line
    - Write ASS file to `WORKING_DIR / name / f"{slug}.ass"`
    - Return the Path to the ASS file
- **Mirror**: `src/shorts/cutter.py:1-9` — Path constant, working dir pattern
- **Validate**: `python -c "from shorts.captions import generate_ass"`

### Task 2: Update `src/shorts/compositor.py` — accept optional subtitle_path

- **File**: `src/shorts/compositor.py`
- **Action**: UPDATE
- **Implement**:
  - Add `subtitle_path: Path | None = None` parameter to `composite_clip`
  - When `subtitle_path` is provided and the file exists:
    - Modify the filter_complex to apply subtitles after vstack:
      ```
      [top][bot]vstack=inputs=2[stacked];[stacked]subtitles='{escaped_path}'[v]
      ```
    - Escape the subtitle path for ffmpeg filter syntax: replace `\` with `/`, escape `:` with `\\:`
  - When `subtitle_path` is None, keep existing behavior (vstack output is `[v]` directly)
- **Mirror**: `src/shorts/compositor.py:17-24` — filter_complex construction
- **Validate**: `python -c "from shorts.compositor import composite_clip"`

### Task 3: Update `src/shorts/pipeline.py` — pass captions through pipeline

- **File**: `src/shorts/pipeline.py`
- **Action**: UPDATE
- **Implement**:
  - Add `captions: bool = False` parameter to `run_pipeline`
  - Import `generate_ass` from `shorts.captions` (at top, with other imports)
  - Import `parse_timestamp` from `shorts.highlights`
  - In the cut/composite loop, when `captions=True`:
    - Call `generate_ass(name, clip.slug, cached, parse_timestamp(clip.start), parse_timestamp(clip.end))` to get the ASS path
    - Pass `subtitle_path=ass_path` to `composite_clip`
  - When `captions=False`, pass `subtitle_path=None` (existing behavior)
  - If `captions=True` but `cached` has no words and no segments, log a warning and skip captions for that clip
- **Mirror**: `src/shorts/pipeline.py:55-75` — existing cut/composite loop
- **Validate**: `python -c "from shorts.pipeline import run_pipeline"`

### Task 4: Update `src/shorts/cli.py` — wire `--captions` on `cut`, fix `run`

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**:
  - **`cut` command**: Add `captions: bool = typer.Option(False, "--captions", help="Burn TikTok-style captions")` parameter
    - When `--captions` is passed, lazy import `from shorts.captions import generate_ass` and `from shorts.transcript import load_cached`
    - Load transcript via `load_cached(name)`. If None and captions requested, error: "No cached transcript for captions. Run 'shorts transcript' first."
    - Before calling `composite_clip`, call `generate_ass(name, clip.slug, transcript, start, end)` to get `ass_path`
    - Pass `subtitle_path=ass_path` to `composite_clip`
    - When captions not requested, pass `subtitle_path=None`
  - **`run` command**: Remove the `if captions: typer.echo("Warning: Captions not yet implemented...")` block
    - Pass `captions=captions` to `run_pipeline`
- **Mirror**: `src/shorts/cli.py:83-130` — existing cut command structure
- **Validate**: `shorts cut --help` shows `--captions`; `shorts run --help` shows `--captions`

### Task 5: Create `tests/test_captions.py` — unit tests for ASS generation

- **File**: `tests/test_captions.py`
- **Action**: CREATE
- **Implement**:
  - Test `_format_ass_time`: 0.0 → "0:00:00.00", 65.5 → "0:01:05.50", 3661.99 → "1:01:01.99"
  - Test `generate_ass` with word-level timestamps:
    - Create Transcript with words spanning 10.0–15.0s, clip_start=10.0, clip_end=15.0
    - Assert ASS file is written to `working/{name}/{slug}.ass`
    - Assert file contains `[Script Info]`, `[V4+ Styles]`, `[Events]`
    - Assert Dialogue lines have times offset to 0:00:00.00 start
  - Test `generate_ass` segment-level fallback:
    - Create Transcript with segments only (words=None)
    - Assert ASS file is generated with segment-level Dialogue lines
  - Test `generate_ass` filters words outside clip window:
    - Provide words from 0–30s, clip is 10–20s
    - Assert only words within 10–20s appear (offset to 0–10s)
  - Test ASS style contains bold white + black stroke:
    - Assert style line contains `&H00FFFFFF` (white) and outline width
- **Mirror**: `tests/test_compositor.py:18-27` — tmp_path + monkeypatch pattern
- **Validate**: `pytest tests/test_captions.py -x`

### Task 6: Update `tests/test_compositor.py` — tests with subtitle_path

- **File**: `tests/test_compositor.py`
- **Action**: UPDATE
- **Implement**:
  - Test `composite_clip` with `subtitle_path` provided:
    - Create a dummy .ass file in tmp_path
    - Capture subprocess args, verify `subtitles=` appears in filter_complex
    - Verify the vstack output feeds into subtitles filter: `vstack=inputs=2[stacked];[stacked]subtitles=`
  - Test `composite_clip` without subtitle_path (None):
    - Verify filter_complex ends with `vstack=inputs=2[v]` (no subtitles filter)
  - Test subtitle path escaping:
    - Use a path with spaces or special chars, verify proper escaping in filter string
- **Mirror**: `tests/test_compositor.py:30-50` — capture subprocess calls pattern
- **Validate**: `pytest tests/test_compositor.py -x`

### Task 7: Update `tests/test_pipeline.py` — tests with captions=True

- **File**: `tests/test_pipeline.py`
- **Action**: UPDATE
- **Implement**:
  - Test pipeline with `captions=True`:
    - Patch `generate_ass` to return a Path
    - Assert `composite_clip` is called with `subtitle_path` set
  - Test pipeline with `captions=False`:
    - Assert `generate_ass` is NOT called
    - Assert `composite_clip` is called with `subtitle_path=None`
- **Mirror**: `tests/test_pipeline.py:28-37` — patch decorator stacking pattern
- **Validate**: `pytest tests/test_pipeline.py -x`

### Task 8: Update `tests/test_cli.py` — update run --captions test, add cut --captions test

- **File**: `tests/test_cli.py`
- **Action**: UPDATE
- **Implement**:
  - Update `test_run_captions_warns`: rename to `test_run_captions_passes_to_pipeline`
    - Assert "not yet implemented" is NOT in output
    - Capture pipeline kwargs, assert `captions=True` is passed
  - Add `test_cut_captions_requires_transcript`:
    - Invoke `["cut", "ep1", "--captions"]` with no cached transcript
    - Assert error about missing transcript
  - Add `test_cut_captions_success`:
    - Monkeypatch `load_cached` to return a transcript, `generate_ass` to return a Path
    - Monkeypatch `cut_clip` and `composite_clip`
    - Assert `composite_clip` called with `subtitle_path`
- **Mirror**: `tests/test_cli.py:42-50` — existing run captions test
- **Validate**: `pytest tests/test_cli.py -x`

### Task 9: Run full test suite and verify

- **File**: N/A
- **Action**: VERIFY
- **Implement**: Run all tests, ensure no regressions
- **Validate**: `pytest`

---

## Validation

```bash
# Import check
python -c "from shorts.captions import generate_ass"

# Unit tests
pytest tests/test_captions.py -v

# Integration tests
pytest tests/test_compositor.py tests/test_pipeline.py tests/test_cli.py -v

# Full suite
pytest

# CLI help
shorts cut --help
shorts run --help
```

---

## Acceptance Criteria

- [ ] AC1: `generate_ass` produces valid ASS file with correct header, styles, and dialogue events
- [ ] AC2: Word-level timestamps produce per-word Dialogue lines (TikTok-style word-by-word)
- [ ] AC3: When `transcript.words` is None, falls back to segment-level captions
- [ ] AC4: All caption timestamps are offset relative to clip start (not absolute)
- [ ] AC5: Compositor applies `subtitles` filter when `subtitle_path` is provided
- [ ] AC6: Compositor behavior unchanged when `subtitle_path` is None
- [ ] AC7: `shorts cut ep1 --captions` burns captions into output
- [ ] AC8: `shorts run ep1 --captions` no longer warns "not yet implemented"
- [ ] AC9: `--captions` on `cut` requires a cached transcript (clear error if missing)
- [ ] AC10: ASS style is bold white text, black stroke (outline), bottom-center aligned
- [ ] All existing tests still pass
- [ ] Follows existing patterns (Path constants, subprocess calls, lazy CLI imports, monkeypatch tests)
