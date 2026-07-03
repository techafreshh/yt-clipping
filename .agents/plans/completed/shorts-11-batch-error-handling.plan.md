# Plan: Batch Processing & Error Handling (SHORTS-11)

## Summary

Enhance the batch processing loop to collect per-clip error details, add a `--fail-fast` flag that stops on first failure, and ensure the CLI exits with code 1 when any clip fails. The fail-forward pattern already exists in `pipeline.py`; this story completes it with proper exit codes, error reporting, and an early-exit option.

## User Story

As a creator
I want batch processing to continue even if individual clips fail (or stop immediately with --fail-fast)
So that one bad timestamp doesn't waste the entire run, and I get clear feedback on what failed

## Metadata

| Field | Value |
|-------|-------|
| Type | ENHANCEMENT |
| Complexity | LOW |
| Systems Affected | pipeline.py, cli.py, tests |
| Jira Issue | SHORTS-11 |

---

## Patterns to Follow

### CLI Flags (bool options)
```python
# SOURCE: src/shorts/cli.py:108
skip_suggest: bool = typer.Option(False, "--skip-suggest", help="Use existing clips"),
```

### Error Handling (batch loop)
```python
# SOURCE: src/shorts/pipeline.py:55-66
for i, clip in enumerate(clips, 1):
    log(f"  Clip {i}/{total}: {clip.slug}")
    try:
        result = cut_clip(name, clip)
    except FileNotFoundError:
        raise
    except RuntimeError as e:
        log(f"    Warning: cut failed - {e}")
        failed += 1
        continue
```

### Exit Codes
```python
# SOURCE: src/shorts/cli.py:120-121
typer.echo(f"Error: {e}", err=True)
raise typer.Exit(1)
```

### Tests (pipeline)
```python
# SOURCE: tests/test_pipeline.py:60-66
def test_per_clip_error_continues(...):
    mock_cut.side_effect = [RuntimeError("ffmpeg fail"), FAKE_CUT]
    result = run_pipeline("ep1", "http://yt.com/v", 50, "model-x", log=MagicMock())
    assert result == {"total": 2, "success": 1, "failed": 1}
```

### Tests (CLI)
```python
# SOURCE: tests/test_cli.py:38-42
def test_run_skip_suggest_uses_existing_clips(monkeypatch):
    monkeypatch.setattr(
        "shorts.pipeline.run_pipeline",
        lambda *a, **kw: {"total": 2, "success": 2, "failed": 0},
    )
    result = runner.invoke(app, ["run", "ep1", "--skip-suggest"])
    assert result.exit_code == 0
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `src/shorts/pipeline.py` | UPDATE | Add `fail_fast` param, collect `errors` list, return it in summary dict |
| `src/shorts/cli.py` | UPDATE | Add `--fail-fast` to `run` and `cut`, exit code 1 on partial failure |
| `tests/test_pipeline.py` | UPDATE | Add tests for fail-fast and errors list |
| `tests/test_cli.py` | UPDATE | Add tests for exit code 1 on partial failure and --fail-fast |

---

## Tasks

Execute in order. Each task is atomic and verifiable.

### Task 1: Add `fail_fast` parameter and `errors` list to `run_pipeline`

- **File**: `src/shorts/pipeline.py`
- **Action**: UPDATE
- **Implement**:
  - Add `fail_fast: bool = False` parameter to `run_pipeline()`
  - Create `errors: list[str] = []` before the batch loop
  - In the `except RuntimeError` blocks, append the error string to `errors` (e.g., `errors.append(f"{clip.slug}: {e}")`)
  - After each failure, if `fail_fast` is True, break out of the loop immediately
  - Add `"errors"` key to the returned dict: `{"total": total, "success": success, "failed": failed, "errors": errors}`
- **Mirror**: `src/shorts/pipeline.py:50-67` — extend existing loop pattern
- **Validate**: `pytest tests/test_pipeline.py`

### Task 2: Add `--fail-fast` flag and exit code 1 to `run` command

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**:
  - Add `fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop on first clip failure")` to the `run` command
  - Pass `fail_fast=fail_fast` to `run_pipeline()`
  - After `run_pipeline` returns, if `summary['failed'] > 0`:
    - Print error details: `for err in summary['errors']: typer.echo(f"  FAILED: {err}", err=True)`
    - Change the "Done" line to show failures: `typer.echo(f"Done: {summary['success']}/{summary['total']} clips produced, {summary['failed']} failed")`
    - `raise typer.Exit(1)`
- **Mirror**: `src/shorts/cli.py:107-121` — follow existing flag and exit patterns
- **Validate**: `pytest tests/test_cli.py`

### Task 3: Add `--fail-fast` flag and exit code 1 to `cut` command

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**:
  - Add `fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop on first clip failure")` to the `cut` command
  - Add `errors: list[str] = []` before the batch loop
  - In the `except RuntimeError` blocks for both cut and composite, append to `errors`
  - After each failure, if `fail_fast` is True, break
  - After the loop, if `len(clips) - success > 0`:
    - Print error details
    - Print summary with failure count
    - `raise typer.Exit(1)`
  - Otherwise print the existing success summary
- **Mirror**: `src/shorts/cli.py:82-103` — extend existing `cut` command loop
- **Validate**: `pytest tests/test_cli.py`

### Task 4: Add pipeline tests for fail-fast and errors list

- **File**: `tests/test_pipeline.py`
- **Action**: UPDATE
- **Implement**:
  - `test_fail_fast_stops_on_first_error`: Set `mock_cut.side_effect = [RuntimeError("fail"), FAKE_CUT]`, call with `fail_fast=True`. Assert `result["success"] == 0`, `result["failed"] == 1`, `result["errors"] == ["clip-one: fail"]`, and `mock_comp.call_count == 0` (second clip never reached)
  - `test_errors_list_populated`: Use existing `test_per_clip_error_continues` pattern but also assert `result["errors"]` contains the error string
  - Update `test_happy_path` assertion to include `"errors": []`
- **Mirror**: `tests/test_pipeline.py:47-66` — follow existing mock/assert pattern
- **Validate**: `pytest tests/test_pipeline.py`

### Task 5: Add CLI tests for exit code 1 and --fail-fast

- **File**: `tests/test_cli.py`
- **Action**: UPDATE
- **Implement**:
  - `test_run_partial_failure_exits_1`: monkeypatch `run_pipeline` to return `{"total": 3, "success": 2, "failed": 1, "errors": ["clip-x: boom"]}`. Assert `exit_code == 1` and "FAILED" in output
  - `test_run_fail_fast_passed_to_pipeline`: monkeypatch `run_pipeline` to capture kwargs, invoke with `--fail-fast`, assert `fail_fast=True` was passed
  - `test_cut_partial_failure_exits_1`: monkeypatch `load_clips` to return FAKE_CLIPS, `cut_clip` to raise RuntimeError on first call. Assert `exit_code == 1`
- **Mirror**: `tests/test_cli.py:38-42` — follow existing monkeypatch/runner pattern
- **Validate**: `pytest tests/test_cli.py`

---

## Validation

```bash
# Run all tests
pytest

# Verify specific modules
pytest tests/test_pipeline.py tests/test_cli.py -v
```

---

## Acceptance Criteria

- [ ] Given 5 clips where clip 3 fails, clips 1, 2, 4, 5 are produced and clip 3 is skipped with error logged
- [ ] Partial failures print summary: `N/M clips produced, K failed`
- [ ] Any clip failure results in exit code 1
- [ ] `--fail-fast` flag stops batch immediately on first failure
- [ ] All existing tests continue to pass
- [ ] `errors` list in return dict contains per-clip failure details
