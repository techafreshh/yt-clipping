# Plan: SHORTS-04 Local Transcript File Loader

## Summary

Add a `--from-file` option to the `shorts transcript` CLI command that loads a transcript from a local JSON or plain text file, validates it, and saves it to the standard `transcripts/` cache. This enables creators to use their own transcriptions without needing the Supadata API.

## User Story

As a creator
I want to load a transcript from a local file
So that I can use my own transcription or a pre-existing caption file without needing the Supadata API

## Metadata

| Field | Value |
|-------|-------|
| Type | NEW_CAPABILITY |
| Complexity | LOW |
| Systems Affected | transcript, cli |
| Jira Issue | SHORTS-04 |

---

## Patterns to Follow

### File Loading & Validation
```python
# SOURCE: src/shorts/transcript.py:48-52
def load_cached(name: str) -> Transcript | None:
    """Load cached transcript from disk, or None if not found."""
    path = TRANSCRIPTS_DIR / f"{name}.json"
    if path.exists():
        return Transcript.model_validate_json(path.read_text())
    return None
```

### CLI Option & Error Handling
```python
# SOURCE: src/shorts/cli.py:12-38
@app.command()
def transcript(
    name: str = typer.Argument(..., help="Source name identifier"),
    youtube_url: Optional[str] = typer.Option(None, "--youtube-url", help="YouTube video URL to fetch transcript from"),
    force: bool = typer.Option(False, "--force", help="Re-fetch even if cached"),
):
    """Fetch or load a transcript for a video."""
    from shorts.config import require, settings
    from shorts.transcript import fetch_transcript, load_cached, save_transcript

    if youtube_url is None:
        raise typer.BadParameter("Provide --youtube-url")
```

### Test Pattern
```python
# SOURCE: tests/test_transcript.py:87-101
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
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `src/shorts/transcript.py` | UPDATE | Add `load_from_file()` function |
| `src/shorts/cli.py` | UPDATE | Add `--from-file` option, mutual exclusivity logic |
| `tests/test_transcript.py` | UPDATE | Add tests for file loading (JSON, txt, not-found, CLI) |

---

## Tasks

### Task 1: Add `load_from_file` function to transcript module

- **File**: `src/shorts/transcript.py`
- **Action**: UPDATE
- **Implement**:
  - Add `import warnings` to imports
  - Add function `load_from_file(file_path: Path) -> Transcript`:
    - If `not file_path.exists()`: raise `FileNotFoundError(f"File not found: {file_path}")`
    - If suffix is `.json`: return `Transcript.model_validate_json(file_path.read_text())`
    - Else (plain text): read text, create `Transcript(segments=[TranscriptSegment(start=0.0, end=0.0, text=content)])`, issue `warnings.warn("Plain text file loaded — timestamps are approximate", stacklevel=2)`, return transcript
- **Mirror**: `src/shorts/transcript.py:48-52` — same read + validate pattern
- **Validate**: `python -c "from shorts.transcript import load_from_file"`

### Task 2: Add `--from-file` option to CLI transcript command

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**:
  - Add parameter: `from_file: Optional[str] = typer.Option(None, "--from-file", help="Local transcript file path (JSON or .txt)")`
  - Replace the `if youtube_url is None` check with mutual exclusivity logic:
    - If both `youtube_url` and `from_file` are provided: raise `typer.BadParameter("Provide --youtube-url or --from-file, not both")`
    - If neither provided: raise `typer.BadParameter("Provide --youtube-url or --from-file")`
  - Add `from_file` branch (before the youtube_url branch):
    - `from pathlib import Path` (lazy import)
    - `from shorts.transcript import load_from_file, save_transcript`
    - Try `load_from_file(Path(from_file))` — catch `FileNotFoundError as e` → raise `typer.BadParameter(str(e))`
    - Call `save_transcript(name, result)`
    - Echo success message with path, return
  - Keep existing youtube_url branch unchanged
- **Mirror**: `src/shorts/cli.py:12-38` — lazy imports, typer.BadParameter pattern
- **Validate**: `shorts transcript --help` shows `--from-file` option

### Task 3: Add tests for local file loading

- **File**: `tests/test_transcript.py`
- **Action**: UPDATE
- **Implement**:
  - Add `import warnings` to imports
  - `test_load_from_file_json(tmp_path)`:
    - Write valid transcript JSON to `tmp_path / "input.json"`
    - Call `load_from_file(tmp_path / "input.json")`
    - Assert segments match
  - `test_load_from_file_txt(tmp_path)`:
    - Write plain text to `tmp_path / "input.txt"`
    - Call `load_from_file(tmp_path / "input.txt")` inside `pytest.warns(UserWarning, match="approximate")`
    - Assert single segment with `start=0.0, end=0.0`, text matches file content
  - `test_load_from_file_not_found(tmp_path)`:
    - Call `load_from_file(tmp_path / "missing.json")`
    - Assert `FileNotFoundError` raised
  - `test_cli_transcript_from_file_json(tmp_path, monkeypatch)`:
    - monkeypatch `TRANSCRIPTS_DIR` to `tmp_path / "out"`
    - Write valid JSON to `tmp_path / "input.json"`
    - Invoke CLI: `["transcript", "vid1", "--from-file", str(tmp_path / "input.json")]`
    - Assert exit_code == 0, output file exists
  - `test_cli_transcript_from_file_txt(tmp_path, monkeypatch)`:
    - Same setup but with `.txt` file
    - Assert exit_code == 0, output file exists
  - `test_cli_transcript_from_file_not_found()`:
    - Invoke CLI with `--from-file nonexistent.json`
    - Assert exit_code != 0, "not found" in output
  - `test_cli_transcript_both_options()`:
    - Invoke CLI with both `--youtube-url` and `--from-file`
    - Assert exit_code != 0, "not both" in output
  - Update `test_cli_transcript_missing_url` → rename to `test_cli_transcript_no_source` (now errors with "Provide --youtube-url or --from-file")
- **Mirror**: `tests/test_transcript.py:87-101` — monkeypatch TRANSCRIPTS_DIR, CliRunner pattern
- **Validate**: `pytest tests/test_transcript.py -v`

---

## Validation

```bash
# Import check
python -c "from shorts.transcript import load_from_file"

# Tests
pytest tests/test_transcript.py -v

# All tests still pass
pytest -v

# CLI smoke test
shorts transcript --help
```

---

## Acceptance Criteria

- [ ] `load_from_file()` exists in `src/shorts/transcript.py`
- [ ] JSON files with `segments` array are loaded and validated via Pydantic
- [ ] Plain `.txt` files are stored as a single segment with `start=0.0, end=0.0` and a warning is emitted
- [ ] Missing file path raises clear "file not found" error
- [ ] `--from-file` and `--youtube-url` are mutually exclusive
- [ ] At least one of `--from-file` or `--youtube-url` is required
- [ ] All tests pass (`pytest -v`)
- [ ] Follows existing patterns (Pydantic validation, typer.BadParameter, lazy imports)
