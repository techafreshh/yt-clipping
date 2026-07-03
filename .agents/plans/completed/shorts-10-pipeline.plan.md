# Plan: End-to-End Pipeline Command (SHORTS-10)

## Summary

Create a `pipeline.py` orchestration module and update the `shorts run` CLI command to execute the full workflow (transcript → suggest → cut/composite) in a single invocation with progress logging. The pipeline reuses all existing modules and accepts flags for `--youtube-url`, `--split`, `--model`, `--skip-suggest`, and `--captions` (deferred to SHORTS-12).

## User Story

As a creator
I want to run the entire pipeline end-to-end with a single command
So that I can go from raw recordings to finished shorts with minimal steps

## Metadata

| Field | Value |
|-------|-------|
| Type | NEW_CAPABILITY |
| Complexity | MEDIUM |
| Systems Affected | cli.py, pipeline.py (new), tests |
| Jira Issue | SHORTS-10 |

---

## Patterns to Follow

### CLI Command Structure
```python
# SOURCE: src/shorts/cli.py:62-100 (cut command)
@app.command()
def cut(
    name: str = typer.Argument(..., help="Source name identifier"),
    split: Optional[int] = typer.Option(None, "--split", help="Screen/camera split percentage (20-80)"),
):
    """Cut and composite shorts from clip specs."""
    from shorts.compositor import composite_clip
    from shorts.config import settings
    from shorts.cutter import cut_clip
    from shorts.highlights import load_clips

    # ... validation, then loop with typer.echo progress
```

### Error Handling
```python
# SOURCE: src/shorts/cli.py:30-40 (transcript command)
    try:
        result = fetch_transcript(youtube_url, api_key)
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
```

### Module Constants
```python
# SOURCE: src/shorts/cutter.py:9-10
RAW_DIR = Path("raw")
WORKING_DIR = Path("working")
```

### Test Pattern (CLI with monkeypatch)
```python
# SOURCE: tests/test_cli.py:24-28
def test_suggest_requires_transcript():
    result = runner.invoke(app, ["suggest", "ep1"])
    assert result.exit_code == 1
    assert "no cached transcript" in result.output.lower()
```

### Test Pattern (monkeypatch module constants + mocks)
```python
# SOURCE: tests/test_compositor.py:24-33
def test_composite_clip_success(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.compositor.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        "shorts.compositor.subprocess.run", lambda *a, **kw: MagicMock()
    )
    clip = Clip(start="01:00", end="01:30", slug="test-clip")
    cut_result = CutResult(camera_path=Path("cam.mp4"), screen_path=Path("scr.mp4"))
    result = composite_clip("ep1", clip, cut_result, 1)
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `src/shorts/pipeline.py` | CREATE | Orchestration logic: transcript → suggest → cut/composite with progress callbacks |
| `src/shorts/cli.py` | UPDATE | Replace `run` stub with full implementation wiring pipeline.py |
| `tests/test_pipeline.py` | CREATE | Unit tests for pipeline orchestration |
| `tests/test_cli.py` | UPDATE | Replace `test_run_stub` with real pipeline CLI tests |

---

## Tasks

Execute in order. Each task is atomic and verifiable.

### Task 1: Create pipeline.py orchestration module

- **File**: `src/shorts/pipeline.py`
- **Action**: CREATE
- **Implement**:
  - Define a `run_pipeline(name, youtube_url, split, model, skip_suggest, log)` function
  - `log` parameter: a callable `(str) -> None` for progress messages (defaults to `print`)
  - Step 1: Fetch/load transcript — call `transcript.load_cached(name)`, if None call `transcript.fetch_transcript(youtube_url, api_key)` + `transcript.save_transcript(name, result)`
  - Step 2: Suggest highlights (unless `skip_suggest=True`) — call `highlights.suggest_highlights()` + `highlights.validate_clips()` + `highlights.save_clips()`
  - Step 3: Load clips, loop through each: `cutter.cut_clip()` → `compositor.composite_clip()`. Log per-clip progress. Continue on RuntimeError per clip, collect failures.
  - Return a summary dataclass/dict: `{"total": N, "success": M, "failed": K}`
  - Raise `RuntimeError` for fatal errors (no transcript URL, API failures in steps 1-2)
  - Raise `FileNotFoundError` for missing raw source files
- **Mirror**: `src/shorts/cli.py:62-100` — same pattern of calling modules, catching errors per clip
- **Validate**: `pip install -e . && python -c "from shorts.pipeline import run_pipeline"`

### Task 2: Update CLI run command

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**:
  - Replace the `run` command stub with full signature:
    ```
    def run(
        name: str = typer.Argument(..., help="Source name identifier"),
        youtube_url: Optional[str] = typer.Option(None, "--youtube-url", help="YouTube URL for transcript"),
        split: Optional[int] = typer.Option(None, "--split", help="Screen/camera split (20-80)"),
        model: Optional[str] = typer.Option(None, "--model", help="OpenRouter model"),
        skip_suggest: bool = typer.Option(False, "--skip-suggest", help="Use existing clips"),
        captions: bool = typer.Option(False, "--captions", help="Burn captions (requires SHORTS-12)"),
    ):
    ```
  - Validate: if not `skip_suggest` and not `youtube_url`, check for cached transcript — if none, error requiring `--youtube-url`
  - If `captions` is True, log warning: "Captions not yet implemented (SHORTS-12), skipping."
  - Resolve `split` from config default if not provided; validate 20-80 range
  - Resolve `model` from config default if not provided
  - Call `pipeline.run_pipeline(name, youtube_url, split, model, skip_suggest, log=typer.echo)`
  - On success: print summary. On error: `typer.echo(f"Error: {e}", err=True)` + `raise typer.Exit(1)`
- **Mirror**: `src/shorts/cli.py:42-60` (suggest command) for config resolution pattern
- **Validate**: `shorts run --help` shows all options

### Task 3: Create tests/test_pipeline.py

- **File**: `tests/test_pipeline.py`
- **Action**: CREATE
- **Implement**:
  - Test `run_pipeline` happy path: monkeypatch all module functions (fetch_transcript, save_transcript, suggest_highlights, validate_clips, save_clips, load_clips, cut_clip, composite_clip). Assert all called in order, returns correct summary.
  - Test `skip_suggest=True`: assert suggest_highlights NOT called, load_clips IS called.
  - Test transcript already cached: assert fetch_transcript NOT called.
  - Test per-clip RuntimeError: one clip raises RuntimeError in cut_clip, pipeline continues, summary shows 1 failed.
  - Test fatal error (no youtube_url and no cached transcript): raises RuntimeError.
  - Test FileNotFoundError from cut_clip propagates (missing raw files = fatal).
- **Mirror**: `tests/test_compositor.py:24-33` for monkeypatch style
- **Validate**: `pytest tests/test_pipeline.py -v`

### Task 4: Update tests/test_cli.py for run command

- **File**: `tests/test_cli.py`
- **Action**: UPDATE
- **Implement**:
  - Remove or replace `test_run_stub` with tests for the real `run` command:
  - `test_run_requires_url_or_cached_transcript`: invoke with no `--youtube-url` and no cached transcript → exit 1
  - `test_run_skip_suggest_uses_existing_clips`: monkeypatch pipeline, pass `--skip-suggest`, assert suggest not called
  - `test_run_captions_warns`: pass `--captions`, assert "not yet implemented" in output
  - `test_run_invalid_split`: pass `--split 95` → exit 1
  - `test_run_success_end_to_end`: monkeypatch pipeline.run_pipeline to return success summary, assert exit 0 and summary in output
- **Mirror**: `tests/test_cli.py:24-28` and `tests/test_compositor.py:108-125` for CLI test patterns
- **Validate**: `pytest tests/test_cli.py -v`

---

## Validation

```bash
# Install
pip install -e .

# Type/import check
python -c "from shorts.pipeline import run_pipeline; from shorts.cli import app"

# Tests
pytest tests/test_pipeline.py tests/test_cli.py -v

# CLI check
shorts run --help
```

---

## Acceptance Criteria

- [ ] `shorts run episode12 --youtube-url <url>` orchestrates transcript → suggest → cut/composite
- [ ] `--skip-suggest` skips LLM call and uses existing clips
- [ ] `--split` and `--model` pass through to relevant stages
- [ ] Progress logging shows step numbers and per-clip progress
- [ ] `--captions` flag accepted but logs "not yet implemented" warning
- [ ] Per-clip errors are caught and reported; pipeline continues
- [ ] Summary printed at end: `Done: N/M clips produced`
- [ ] All existing tests still pass
- [ ] New tests cover happy path, skip-suggest, error cases
