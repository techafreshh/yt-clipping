# Plan: SHORTS-08 9:16 Vertical Compositor

## Summary

Create `src/shorts/compositor.py` that takes the cut camera and screen segments from the working directory and composites them into a vertical 9:16 (1080×1920) output using ffmpeg filter chains. Screen goes on top, camera on bottom, with a configurable split ratio. Audio comes from the camera track. Output goes to `output/{name}/{name}_short_{NN}_{slug}.mp4`. Update the `cut` CLI command to composite after cutting, producing final output files.

## User Story

As a creator
I want my shorts to be vertical 9:16 with screen on top and camera on bottom
So that they're optimized for YouTube Shorts and TikTok without manual editing

## Metadata

| Field | Value |
|-------|-------|
| Type | NEW_CAPABILITY |
| Complexity | MEDIUM |
| Systems Affected | compositor (new), cli, cutter, config, tests |
| Jira Issue | SHORTS-08 |

---

## Patterns to Follow

### Directory Constants & Pydantic Models
```python
# SOURCE: src/shorts/cutter.py:1-12
import subprocess
from pathlib import Path
from pydantic import BaseModel

RAW_DIR = Path("raw")
WORKING_DIR = Path("working")

class CutResult(BaseModel):
    camera_path: Path
    screen_path: Path
```

### Subprocess ffmpeg Calls with Error Handling
```python
# SOURCE: src/shorts/cutter.py:16-23
def _get_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr}")
    return float(result.stdout.strip())
```

### CLI Command with Lazy Imports and Batch Error Handling
```python
# SOURCE: src/shorts/cli.py:80-100
@app.command()
def cut(name: str = typer.Argument(..., help="Source name identifier")):
    """Cut and composite shorts from clip specs."""
    from shorts.cutter import cut_clip
    from shorts.highlights import load_clips

    clips = load_clips(name)
    if clips is None:
        typer.echo("Error: no clips found. Run 'shorts suggest' first.", err=True)
        raise typer.Exit(1)

    success = 0
    for i, clip in enumerate(clips, 1):
        typer.echo(f"Cutting clip {i}/{len(clips)}: {clip.slug}")
        try:
            cut_clip(name, clip)
            success += 1
        except FileNotFoundError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)
        except RuntimeError as e:
            typer.echo(f"Warning: {e}", err=True)

    typer.echo(f"Done: {success}/{len(clips)} clips cut")
```

### Tests — Monkeypatch + subprocess mocking
```python
# SOURCE: tests/test_cutter.py:22-27
def test_get_duration_success(monkeypatch):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "45.5\n"
    monkeypatch.setattr("shorts.cutter.subprocess.run", lambda *a, **kw: mock_result)
    assert _get_duration(Path("test.mp4")) == 45.5
```

### Tests — CLI Integration
```python
# SOURCE: tests/test_cutter.py:137-149
def test_cli_cut_success(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    clips = [{"start": "01:00", "end": "01:30", "slug": "clip-one"}]
    (tmp_path / "ep1.json").write_text(json.dumps(clips))

    dummy_result = CutResult(camera_path=Path("a.mp4"), screen_path=Path("b.mp4"))
    monkeypatch.setattr("shorts.cutter.cut_clip", lambda name, clip: dummy_result)

    result = runner.invoke(app, ["cut", "ep1"])
    assert result.exit_code == 0
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `src/shorts/compositor.py` | CREATE | 9:16 compositing logic with ffmpeg filter chain |
| `src/shorts/cli.py` | UPDATE | Add `--split` option to `cut` command, call compositor after cutting |
| `tests/test_compositor.py` | CREATE | Unit tests for compositor + CLI integration |

---

## Tasks

Execute in order. Each task is atomic and verifiable.

### Task 1: Create `src/shorts/compositor.py` with constants and composite function

- **File**: `src/shorts/compositor.py`
- **Action**: CREATE
- **Implement**:
  - Import `subprocess`, `Path` from pathlib
  - Define `OUTPUT_DIR = Path("output")`
  - Define `WIDTH = 1080` and `HEIGHT = 1920`
  - Define function `composite_clip(name: str, clip, cut_result, index: int, split: int = 50) -> Path`:
    - Validate split is 20–80; raise `ValueError` if not
    - Calculate `top_h = int(HEIGHT * split / 100)` and `bot_h = HEIGHT - top_h`
    - Build ffmpeg filter_complex string:
      ```
      [0:v]scale={WIDTH}:{top_h}:force_original_aspect_ratio=decrease,pad={WIDTH}:{top_h}:(ow-iw)/2:(oh-ih)/2[top];
      [1:v]scale={WIDTH}:{bot_h}:force_original_aspect_ratio=decrease,pad={WIDTH}:{bot_h}:(ow-iw)/2:(oh-ih)/2[bot];
      [top][bot]vstack=inputs=2[v]
      ```
    - Create output dir: `OUTPUT_DIR / name` (parents=True, exist_ok=True)
    - Output path: `OUTPUT_DIR / name / f"{name}_short_{index:02d}_{clip.slug}.mp4"`
    - Build ffmpeg command:
      ```
      ffmpeg -y -i {cut_result.screen_path} -i {cut_result.camera_path}
        -filter_complex "{filter}" -map "[v]" -map 1:a
        -c:v libx264 -preset fast -crf 18 -c:a aac -pix_fmt yuv420p
        {output_path}
      ```
    - Run with `subprocess.run(cmd, capture_output=True, text=True, check=True)`
    - On `CalledProcessError`, raise `RuntimeError(f"Compositing failed: {e.stderr}")`
    - Return `output_path`
- **Mirror**: `src/shorts/cutter.py:26-43` — subprocess ffmpeg pattern with error handling
- **Validate**: `python -c "from shorts.compositor import composite_clip, OUTPUT_DIR"`

### Task 2: Update `cut` CLI command to add `--split` and call compositor

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**:
  - Add `split: int = typer.Option(None, "--split", help="Screen/camera split percentage (20-80)")` parameter to `cut` command
  - Inside the command, lazy import `from shorts.compositor import composite_clip`
  - Resolve split: `use_split = split if split is not None else settings.default_split` (import settings)
  - After `cut_clip(name, clip)` succeeds, call `composite_clip(name, clip, result, i, use_split)` where `result` is the `CutResult` returned by `cut_clip`
  - Update echo to show compositing: `typer.echo(f"  → {output_path.name}")`
  - Catch `ValueError` from compositor (invalid split) and exit with error
- **Mirror**: `src/shorts/cli.py:80-100` — existing cut command structure
- **Validate**: `shorts cut --help` shows `--split` option

### Task 3: Create `tests/test_compositor.py` — unit tests

- **File**: `tests/test_compositor.py`
- **Action**: CREATE
- **Implement**:
  - Test `composite_clip` success: monkeypatch `subprocess.run` to succeed, monkeypatch `OUTPUT_DIR` to tmp_path. Assert output path is returned with correct naming pattern `{name}_short_01_{slug}.mp4`.
  - Test `composite_clip` builds correct filter for 50/50 split: capture the subprocess args, verify `scale=1080:960` appears for both top and bot.
  - Test `composite_clip` builds correct filter for 60/40 split: verify `scale=1080:1152` for top and `scale=1080:768` for bot.
  - Test `composite_clip` invalid split (<20 or >80): assert `ValueError` raised.
  - Test `composite_clip` ffmpeg failure: monkeypatch `subprocess.run` to raise `CalledProcessError`. Assert `RuntimeError` with "Compositing failed".
  - Test correct output naming with index: pass index=3, assert `_short_03_` in output path.
  - Test audio mapping: verify `-map 1:a` in the ffmpeg command (audio from camera input).
- **Mirror**: `tests/test_cutter.py:22-90` — monkeypatch subprocess pattern
- **Validate**: `pytest tests/test_compositor.py -x`

### Task 4: Create `tests/test_compositor.py` — CLI integration tests

- **File**: `tests/test_compositor.py`
- **Action**: UPDATE (append)
- **Implement**:
  - Test CLI `cut` with `--split 60`: monkeypatch `cut_clip` and `composite_clip`, invoke `["cut", "ep1", "--split", "60"]`. Assert exit_code 0 and composite was called with split=60.
  - Test CLI `cut` with invalid `--split 90`: monkeypatch `cut_clip` to succeed, let `composite_clip` raise ValueError. Assert exit_code 1 and error message about valid range.
  - Test CLI `cut` default split uses config: monkeypatch `settings.default_split` to 55, invoke without `--split`. Assert composite called with split=55.
  - Test CLI `cut` compositing failure continues batch: two clips, first composite raises RuntimeError, second succeeds. Assert "1/2" in output.
- **Mirror**: `tests/test_cutter.py:127-175` — CLI test patterns
- **Validate**: `pytest tests/test_compositor.py -x`

### Task 5: Run full test suite and verify

- **File**: N/A
- **Action**: VERIFY
- **Implement**: Run all tests, ensure no regressions
- **Validate**: `pytest`

---

## Validation

```bash
# Import check
python -c "from shorts.compositor import composite_clip, OUTPUT_DIR"

# Tests
pytest tests/test_compositor.py -v

# All tests still pass
pytest

# CLI help shows --split
shorts cut --help
```

---

## Acceptance Criteria

- [ ] AC1: Given cut camera and screen segments, when composited with default split (50/50), then output is exactly 1080×1920
- [ ] AC2: Given `--split 60`, when composited, then screen occupies 60% (1152px) and camera 40% (768px)
- [ ] AC3: Given the output file, when inspected, then it is H.264 video + AAC audio, yuv420p pixel format
- [ ] AC4: Given source aspect ratios that don't perfectly fill their space, then black bars pad (no stretching)
- [ ] AC5: Given the output, audio comes from the camera track and is in sync
- [ ] AC6: Output naming follows `output/{name}/{name}_short_{NN}_{slug}.mp4`
- [ ] AC7: Split values outside 20–80 raise a clear error
- [ ] All existing tests still pass
- [ ] Follows existing patterns (Path constants, subprocess calls, lazy CLI imports, monkeypatch tests)
