# Plan: SHORTS-13 README & Documentation

## Summary

Create a comprehensive `README.md` at the project root covering prerequisites, installation, configuration, folder conventions, full workflow walkthrough (manual + AI modes), CLI reference, and troubleshooting. Also create `clips/example.json` demonstrating the expected clip spec format. The `.env.example` already exists and is complete.

## User Story

As a developer
I want comprehensive documentation
So that I (or anyone else) can set up and use the tool without external guidance

## Metadata

| Field | Value |
|-------|-------|
| Type | NEW_CAPABILITY |
| Complexity | LOW |
| Systems Affected | docs (README.md, clips/example.json) |
| Jira Issue | SHORTS-13 |

---

## Patterns to Follow

### CLI Commands (from cli.py)
```python
# SOURCE: src/shorts/cli.py:1-10
# Commands: transcript, suggest, cut, run, config
# All use typer with Argument for name, Options for flags
```

### Folder Conventions (from PRD)
```
# SOURCE: .agents/PRDs/PRD.md — Directory Structure section
raw/{source_name}_camera.mp4
raw/{source_name}_screen.mp4
transcripts/{source_name}.json
clips/{source_name}.json
output/{source_name}/{source_name}_short_{NN}_{slug}.mp4
```

### Clip Spec Format (from highlights.py)
```python
# SOURCE: src/shorts/highlights.py:16-24
class Clip(BaseModel):
    start: str
    end: str
    slug: str
    hook: Optional[str] = None
    # slug must match ^[a-z0-9-]+$
```

### .env Configuration (from .env.example)
```
# SOURCE: .env.example
SUPADATA_API_KEY=your_supadata_key_here
OPENROUTER_API_KEY=your_openrouter_key_here
DEFAULT_MODEL=anthropic/claude-sonnet-4
DEFAULT_SPLIT=50
DEFAULT_CLIP_DURATION_MIN=30
DEFAULT_CLIP_DURATION_MAX=60
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `README.md` | CREATE | Comprehensive project documentation |
| `clips/example.json` | CREATE | Example clip spec demonstrating format |

---

## Tasks

Execute in order. Each task is atomic and verifiable.

### Task 1: Create `clips/example.json`

- **File**: `clips/example.json`
- **Action**: CREATE
- **Implement**: Create a sample clip spec JSON array with 2 example clips demonstrating:
  - `HH:MM:SS` timestamp format
  - Valid kebab-case slugs
  - Optional hook field (one with, one without)
  - Realistic durations (30-60s range)
- **Mirror**: `src/shorts/highlights.py:16-24` — follow the Clip model schema
- **Validate**: `python -c "import json; json.load(open('clips/example.json'))"`

### Task 2: Create `README.md`

- **File**: `README.md`
- **Action**: CREATE
- **Implement**: Write a comprehensive README covering these sections:
  1. **Title & one-line description** — YouTube Shorts Repurposing Workflow
  2. **Features** — bullet list of capabilities
  3. **Prerequisites** — Python 3.11+, ffmpeg on PATH, API keys (Supadata, OpenRouter)
  4. **Installation** — `pip install -e .` from project root
  5. **Configuration** — copy `.env.example` to `.env`, fill in keys, explain each variable
  6. **Folder Conventions** — explain `raw/`, `transcripts/`, `clips/`, `output/`, `working/` with naming patterns
  7. **Quick Start** — minimal steps to produce first short
  8. **Workflow: Manual Mode** — create clips JSON manually, run `shorts cut`
  9. **Workflow: AI Mode** — fetch transcript, suggest highlights, cut
  10. **Workflow: Full Pipeline** — single `shorts run` command with all flags
  11. **CLI Reference** — table or list of all commands with their options (transcript, suggest, cut, run, config)
  12. **Clip Spec Format** — JSON schema with example, explain fields
  13. **Captions** — how `--captions` works, word-level vs segment-level
  14. **Troubleshooting** — common issues: ffmpeg not found, missing audio, sync mismatch, OpenRouter errors, Supadata errors, split out of range
  15. **Development** — `pip install -e ".[dev]"`, `pytest`, project structure
- **Mirror**: `.agents/PRDs/PRD.md` — use the CLI reference and architecture sections as source of truth
- **Validate**: Visually confirm all CLI commands from `shorts --help` are documented

### Task 3: Verify CLI help matches README

- **File**: N/A (verification only)
- **Action**: VERIFY
- **Implement**: Run `shorts --help` and each subcommand's `--help` to confirm all documented options exist
- **Validate**: `python -c "import sys; sys.argv=['shorts','--help']; from shorts.cli import app; app()"`

---

## Validation

```bash
# Verify example.json is valid JSON matching Clip schema
python -c "from shorts.highlights import Clip; import json; [Clip(**c) for c in json.load(open('clips/example.json'))]"

# Verify README exists and is non-trivial
python -c "assert len(open('README.md').read()) > 1000, 'README too short'"

# Run existing tests to ensure nothing broken
pytest
```

---

## Acceptance Criteria

- [ ] `README.md` covers: prerequisites, installation, .env setup, folder conventions, full workflow walkthrough (manual + AI mode), CLI reference
- [ ] `.env.example` when copied to `.env` and filled in allows the tool to run without config errors (already exists — verify documented)
- [ ] `clips/example.json` demonstrates the expected clip spec format with valid entries
- [ ] All subcommands from `shorts --help` are documented in the README
- [ ] Troubleshooting section covers: ffmpeg not found, missing audio, sync mismatch, OpenRouter errors, Supadata errors
