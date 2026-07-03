# Plan: AI Highlight Suggestions via OpenRouter

## Summary

Build the `highlights.py` module that sends a transcript to an LLM via OpenRouter's chat completions API and parses the response into validated clip specs. Wire it into the `shorts suggest` CLI command with `--model` and `--count` options. Includes retry on malformed JSON and timestamp validation against transcript bounds.

## User Story

As a creator
I want AI to suggest clip-worthy moments from my transcript
So that I can discover engaging segments I might have missed

## Metadata

| Field | Value |
|-------|-------|
| Type | NEW_CAPABILITY |
| Complexity | MEDIUM |
| Systems Affected | highlights module, CLI |
| Jira Issue | SHORTS-05 |

---

## Patterns to Follow

### Module Structure & Imports
```python
# SOURCE: src/shorts/transcript.py:1-10
"""Transcript fetching via Supadata API."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import httpx
from pydantic import BaseModel
```

### Directory Constants & Pydantic Models
```python
# SOURCE: src/shorts/transcript.py:12-24
TRANSCRIPTS_DIR = Path("transcripts")
API_URL = "https://api.supadata.ai/v1/transcript"

class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str

class Transcript(BaseModel):
    segments: list[TranscriptSegment]
    words: Optional[list[TranscriptSegment]] = None
```

### HTTP Call with Retry
```python
# SOURCE: src/shorts/transcript.py:27-47
def fetch_transcript(youtube_url: str, api_key: str) -> Transcript:
    """Fetch transcript from Supadata API with one retry on 5xx."""
    with httpx.Client(timeout=30) as client:
        for attempt in range(2):
            resp = client.get(...)
            if resp.status_code >= 500 and attempt == 0:
                time.sleep(2)
                continue
            break
        if resp.status_code != 200:
            raise RuntimeError(f"... error {resp.status_code}: {resp.text}...")
```

### CLI Command Pattern
```python
# SOURCE: src/shorts/cli.py:10-50
@app.command()
def transcript(
    name: str = typer.Argument(..., help="Source name identifier"),
    youtube_url: Optional[str] = typer.Option(None, "--youtube-url", help="..."),
):
    """Fetch or load a transcript for a video."""
    from shorts.config import require, settings
    from shorts.transcript import ...

    api_key = require(settings, "supadata_api_key")
    try:
        result = fetch_transcript(youtube_url, api_key)
    except RuntimeError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
```

### Config Require Pattern
```python
# SOURCE: src/shorts/config.py:20-25
def require(settings: Settings, field_name: str) -> str:
    """Return field value or raise if missing."""
    value = getattr(settings, field_name)
    if value is None:
        raise typer.BadParameter(f"Missing required config: {field_name.upper()}. Set it in .env")
    return value
```

### Test Pattern (Mock HTTP + CLI Runner)
```python
# SOURCE: tests/test_transcript.py:55-72
def test_fetch_transcript_success(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"content": SAMPLE_SEGMENTS}

    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.return_value = mock_resp

    monkeypatch.setattr("shorts.transcript.httpx.Client", lambda **kw: mock_client)
    result = fetch_transcript("https://youtube.com/watch?v=abc", "sk-key")
    assert len(result.segments) == 2
```

### CLI Test Pattern
```python
# SOURCE: tests/test_transcript.py:100-115
def test_cli_transcript_fetches_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path)
    monkeypatch.setenv("SUPADATA_API_KEY", "sk-test")

    import shorts.config
    from shorts.config import Settings
    monkeypatch.setattr(shorts.config, "settings", Settings(_env_file=None))

    t = Transcript(segments=[...])
    monkeypatch.setattr("shorts.transcript.fetch_transcript", lambda url, key: t)

    result = runner.invoke(app, ["transcript", "vid1", "--youtube-url", "..."])
    assert result.exit_code == 0
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `src/shorts/highlights.py` | CREATE | Clip model, OpenRouter API call, response parsing, validation, save/load |
| `src/shorts/cli.py` | UPDATE | Wire `suggest` command with --model, --count options |
| `tests/test_highlights.py` | CREATE | Unit tests for highlights module + CLI integration |

---

## Tasks

Execute in order. Each task is atomic and verifiable.

### Task 1: Create Clip model and highlights module skeleton

- **File**: `src/shorts/highlights.py`
- **Action**: CREATE
- **Implement**:
  - Module docstring: `"""AI highlight suggestions via OpenRouter."""`
  - Imports: `from __future__ import annotations`, `json`, `time`, `Path`, `Optional`, `httpx`, `BaseModel`, `field_validator`
  - Constants: `CLIPS_DIR = Path("clips")`, `OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"`
  - Pydantic model `Clip(BaseModel)`: fields `start: str`, `end: str`, `slug: str`, `hook: Optional[str] = None`
  - Add `field_validator` on `slug` to enforce `^[a-z0-9-]+$`
  - Helper `parse_timestamp(ts: str) -> float` supporting `HH:MM:SS`, `MM:SS`, and raw float seconds
  - Helper `validate_clips(clips: list[Clip], max_duration: float) -> list[Clip]` that:
    - Converts start/end to seconds
    - Rejects clips where end <= start (raises `ValueError`)
    - Rejects clips where end > max_duration (raises `ValueError`)
    - Returns valid clips (clips between 15–90s pass; outside that range get a warning logged but are kept)
- **Mirror**: `src/shorts/transcript.py:1-24` — module structure, constants, Pydantic models
- **Validate**: `python -c "from shorts.highlights import Clip, parse_timestamp, validate_clips"`

### Task 2: Implement OpenRouter API call with retry

- **File**: `src/shorts/highlights.py`
- **Action**: UPDATE (append)
- **Implement**:
  - Function `suggest_highlights(transcript_text: str, api_key: str, model: str, count: int) -> list[Clip]`:
    - Build system prompt instructing LLM to return JSON `{"clips": [...]}` with `start`, `end`, `slug`, `hook` fields; clips should be 30–60s, self-contained moments
    - POST to OpenRouter with `response_format: {"type": "json_object"}`, `Authorization: Bearer {api_key}`
    - On success: parse JSON from `choices[0].message.content`
    - On parse failure (invalid JSON or missing keys): retry once with same request
    - On second failure: raise `RuntimeError` with the raw response text for debugging
    - On HTTP error: raise `RuntimeError` with status code and response text
    - Return `list[Clip]` parsed from response
  - Function `save_clips(name: str, clips: list[Clip]) -> Path`:
    - Save to `CLIPS_DIR / f"{name}.json"` as JSON array
  - Function `load_clips(name: str) -> list[Clip] | None`:
    - Load from disk or return None
- **Mirror**: `src/shorts/transcript.py:27-47` — httpx Client, retry loop, error raising
- **Validate**: `python -c "from shorts.highlights import suggest_highlights, save_clips, load_clips"`

### Task 3: Wire suggest CLI command

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**:
  - Replace the `suggest` stub with full implementation:
    - Parameters: `name` (Argument), `--model` (Option, default None → uses config default_model), `--count` (Option, default 5)
    - Load transcript via `load_cached(name)` — error if not found
    - Require `openrouter_api_key` from config
    - Build transcript text from segments (join segment texts)
    - Call `suggest_highlights(text, api_key, model, count)`
    - Validate clips against transcript max timestamp
    - Save clips via `save_clips(name, clips)`
    - Echo summary: number of clips saved and path
  - Handle `RuntimeError` with `typer.echo(err, err=True)` + `typer.Exit(1)`
- **Mirror**: `src/shorts/cli.py:10-50` — transcript command pattern
- **Validate**: `shorts suggest --help` shows --model and --count options

### Task 4: Write unit tests for highlights module

- **File**: `tests/test_highlights.py`
- **Action**: CREATE
- **Implement**:
  - Test `parse_timestamp` with `"01:30:00"` → 5400.0, `"02:15"` → 135.0, `"45.5"` → 45.5
  - Test `Clip` model valid construction
  - Test `Clip` model rejects invalid slug (e.g., `"Bad Slug!"`)
  - Test `validate_clips` rejects end <= start
  - Test `validate_clips` rejects end > max_duration
  - Test `validate_clips` passes valid clips
  - Test `suggest_highlights` success with mocked httpx (return valid JSON)
  - Test `suggest_highlights` retries on malformed JSON then succeeds
  - Test `suggest_highlights` raises on second parse failure
  - Test `suggest_highlights` raises on HTTP error
  - Test `save_clips` and `load_clips` round-trip (using tmp_path + monkeypatch)
  - Test CLI `shorts suggest` end-to-end with mocked API and cached transcript
  - Test CLI `shorts suggest` errors when no transcript cached
- **Mirror**: `tests/test_transcript.py:1-150` — mock patterns, CLI runner, monkeypatch
- **Validate**: `pytest tests/test_highlights.py -v`

---

## Validation

```bash
# Type/import check
python -c "from shorts.highlights import Clip, suggest_highlights, save_clips, load_clips, parse_timestamp, validate_clips"

# Lint
ruff check src/shorts/highlights.py tests/test_highlights.py

# Tests
pytest tests/test_highlights.py -v

# Full test suite
pytest
```

---

## Acceptance Criteria

- [ ] `shorts suggest episode12 --model anthropic/claude-sonnet-4 --count 5` creates `clips/episode12.json` with 5 clip entries (when transcript is cached and API responds)
- [ ] Each clip has valid `start`, `end`, `slug`, and `hook` fields
- [ ] Timestamps validated against transcript time range; clips between 15–90s accepted
- [ ] Malformed LLM JSON triggers one retry; second failure shows raw response in error
- [ ] `--model` defaults to `DEFAULT_MODEL` from config when not specified
- [ ] All tests pass (`pytest`)
- [ ] Lint passes (`ruff check`)
