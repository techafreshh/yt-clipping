# Plan: SHORTS-03 Transcript Fetching via Supadata API

## Summary

Create a transcript module that fetches timestamped transcripts from YouTube videos via the Supadata API, caches them to disk as JSON, and wires into the existing CLI `transcript` command with `--youtube-url` and `--force` options. Includes retry on 5xx and clear error messaging.

## User Story

As a creator
I want to fetch my video's transcript automatically via its YouTube URL
So that I don't need to manually transcribe or export captions

## Metadata

| Field | Value |
|-------|-------|
| Type | NEW_CAPABILITY |
| Complexity | MEDIUM |
| Systems Affected | transcript, cli |
| Jira Issue | SHORTS-03 |

---

## Patterns to Follow

### Module Structure & Naming
```python
# SOURCE: src/shorts/config.py:1-6
"""Configuration module using Pydantic BaseSettings."""

from __future__ import annotations

from typing import Optional
```

### Pydantic Models
```python
# SOURCE: src/shorts/config.py:11-21
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    supadata_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    default_model: str = "anthropic/claude-sonnet-4"
    default_split: int = 50
    default_clip_duration_min: int = 30
    default_clip_duration_max: int = 60
```

### Error Handling
```python
# SOURCE: src/shorts/config.py:24-28
def require(settings: Settings, field_name: str) -> str:
    """Return field value or raise if missing."""
    value = getattr(settings, field_name)
    if value is None:
        raise typer.BadParameter(f"Missing required config: {field_name.upper()}. Set it in .env")
    return value
```

### CLI Command with Lazy Imports
```python
# SOURCE: src/shorts/cli.py:30-38
@app.command()
def config():
    """Print resolved configuration (secrets masked)."""
    from shorts.config import mask, settings

    for name in settings.model_fields:
        value = getattr(settings, name)
        if value is not None and ("key" in name or "api" in name):
            typer.echo(f"{name.upper()}: {mask(str(value))}")
        else:
            typer.echo(f"{name.upper()}: {value}")
```

### Tests
```python
# SOURCE: tests/test_config.py:1-12
"""Tests for the configuration module."""

import pytest
from click.exceptions import BadParameter
from typer.testing import CliRunner

from shorts.cli import app
from shorts.config import Settings, mask, require

runner = CliRunner()
```

```python
# SOURCE: tests/test_config.py:23-27
def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("SUPADATA_API_KEY", "sk-test123")
    monkeypatch.setenv("DEFAULT_SPLIT", "75")
    s = Settings(_env_file=None)
    assert s.supadata_api_key == "sk-test123"
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `src/shorts/transcript.py` | CREATE | Pydantic models + Supadata fetch + caching + retry |
| `src/shorts/cli.py` | UPDATE | Wire --youtube-url and --force into transcript command |
| `tests/test_transcript.py` | CREATE | Unit tests for models, fetch, cache, retry, errors, CLI |

---

## Tasks

### Task 1: Create transcript module with Pydantic models

- **File**: `src/shorts/transcript.py`
- **Action**: CREATE
- **Implement**:
  - Module docstring: `"""Transcript fetching via Supadata API."""`
  - `from __future__ import annotations`
  - Imports: `json, time, Path` from stdlib; `httpx`; `pydantic.BaseModel`; `Optional` from typing
  - Define `TranscriptSegment(BaseModel)`: `start: float`, `end: float`, `text: str`
  - Define `Transcript(BaseModel)`: `segments: list[TranscriptSegment]`, `words: Optional[list[TranscriptSegment]] = None`
  - Define `fetch_transcript(youtube_url: str, api_key: str) -> Transcript`:
    - `GET https://api.supadata.ai/v1/transcript` with params `url=youtube_url`
    - Header: `x-api-key: {api_key}`
    - Timeout: 30s
    - On 5xx: sleep 2s, retry once
    - On other non-200: raise `RuntimeError` with status code and message suggesting API key check
    - Parse response JSON `content` array into `segments`; if response has word-level data, populate `words`
    - Return `Transcript` instance
  - Define `load_cached(name: str) -> Transcript | None`:
    - Check `transcripts/{name}.json` exists
    - If yes, read and return `Transcript.model_validate_json(path.read_text())`
    - If no, return None
  - Define `save_transcript(name: str, transcript: Transcript) -> Path`:
    - Ensure `transcripts/` dir exists (`mkdir(parents=True, exist_ok=True)`)
    - Write `transcript.model_dump_json(indent=2)` to `transcripts/{name}.json`
    - Return the path
- **Mirror**: `src/shorts/config.py:1-6` — module docstring + imports style
- **Validate**: `python -c "from shorts.transcript import Transcript, fetch_transcript"`

### Task 2: Wire CLI transcript command

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**:
  - Replace the `transcript` command signature and body:
    - Add `youtube_url: Optional[str] = typer.Option(None, "--youtube-url", help="YouTube video URL to fetch transcript from")`
    - Add `force: bool = typer.Option(False, "--force", help="Re-fetch even if cached")`
    - Body (lazy imports):
      - `from shorts.transcript import fetch_transcript, load_cached, save_transcript`
      - `from shorts.config import require, settings`
      - If `youtube_url` is None: raise `typer.BadParameter("Provide --youtube-url")`
      - If not `force`: check `load_cached(name)` — if exists, echo "Using cached transcript" and return
      - Call `require(settings, "supadata_api_key")` to get key
      - Call `fetch_transcript(youtube_url, api_key)`
      - Call `save_transcript(name, transcript)`
      - Echo success message with path
    - Wrap fetch in try/except RuntimeError → echo error and raise `typer.Exit(1)`
- **Mirror**: `src/shorts/cli.py:30-38` — lazy import pattern inside command
- **Validate**: `shorts transcript --help` shows --youtube-url and --force options

### Task 3: Write tests for transcript module

- **File**: `tests/test_transcript.py`
- **Action**: CREATE
- **Implement**:
  - `test_transcript_model_valid()` — construct Transcript with segments list, assert fields accessible
  - `test_transcript_model_optional_words()` — construct without words, assert words is None
  - `test_save_and_load_cached(tmp_path, monkeypatch)` — monkeypatch cwd or pass path, save a Transcript, load_cached returns same data
  - `test_load_cached_returns_none(tmp_path, monkeypatch)` — no file exists, returns None
  - `test_fetch_transcript_success(monkeypatch)` — monkeypatch `httpx.Client.get` to return mock 200 response with segments JSON, assert Transcript returned
  - `test_fetch_transcript_retries_on_5xx(monkeypatch)` — first call returns 500, second returns 200, assert success after retry
  - `test_fetch_transcript_error_on_4xx(monkeypatch)` — return 401, assert RuntimeError raised with status code
  - `test_cli_transcript_fetches_and_caches(monkeypatch, tmp_path)` — monkeypatch fetch_transcript, set env vars, invoke CLI, assert file created
  - `test_cli_transcript_uses_cache(monkeypatch, tmp_path)` — pre-create cached file, invoke CLI without --force, assert fetch not called
  - `test_cli_transcript_force_refetches(monkeypatch, tmp_path)` — pre-create cached file, invoke with --force, assert fetch called
  - `test_cli_transcript_missing_url()` — invoke without --youtube-url, assert error
- **Mirror**: `tests/test_config.py:1-12` — same imports/runner pattern; `tests/test_config.py:23-27` — monkeypatch.setenv style
- **Validate**: `pytest tests/test_transcript.py -v`

---

## Validation

```bash
# Import check
python -c "from shorts.transcript import Transcript, fetch_transcript"

# Tests
pytest tests/test_transcript.py -v

# All tests still pass
pytest -v

# CLI smoke test
shorts transcript --help
```

---

## End-to-End Tests

1. **Fetch and cache**: Set valid `SUPADATA_API_KEY` in `.env`, run `shorts transcript test1 --youtube-url https://youtube.com/watch?v=dQw4w9WgXcQ` → `transcripts/test1.json` created with segments
2. **Cache hit**: Run same command again → prints "Using cached transcript", no API call
3. **Force refetch**: Run with `--force` → re-fetches and overwrites
4. **Missing API key**: Remove `SUPADATA_API_KEY` from `.env`, run command → clear error naming the missing variable
5. **Invalid URL / API error**: Use bad URL → clear error with HTTP status

---

## Acceptance Criteria

- [ ] `src/shorts/transcript.py` exists with `Transcript`, `TranscriptSegment` models, `fetch_transcript()`, `load_cached()`, `save_transcript()`
- [ ] `shorts transcript <name> --youtube-url <url>` fetches and saves transcript
- [ ] Cached transcript reused unless `--force` passed
- [ ] One retry on 5xx with 2s backoff
- [ ] Clear error on non-200 responses mentioning HTTP status and API key check
- [ ] Word-level timestamps stored when available (`words` field)
- [ ] All tests pass (`pytest -v`)
- [ ] Follows existing patterns (Pydantic models, typer.BadParameter, lazy imports)
