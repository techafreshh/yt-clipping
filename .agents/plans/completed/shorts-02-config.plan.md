# Plan: SHORTS-02 Configuration Loader

## Summary

Create a configuration module using Pydantic BaseSettings that loads API keys and defaults from `.env`. All fields are Optional (lazy validation) — errors only surface when a command actually needs a missing key. The `shorts config` command prints all settings with secrets masked.

## User Story

As a developer
I want a configuration module that loads API keys and defaults from `.env`
So that all modules can access settings consistently without hardcoding values

## Metadata

| Field | Value |
|-------|-------|
| Type | NEW_CAPABILITY |
| Complexity | LOW |
| Systems Affected | config, cli, pyproject.toml |
| Jira Issue | N/A |

---

## Patterns to Follow

### Module Docstring & Imports
```python
# SOURCE: src/shorts/cli.py:1-3
"""CLI entry point for the shorts tool."""

import typer
```

### CLI Command Pattern
```python
# SOURCE: src/shorts/cli.py:30-32
@app.command()
def config():
    """Print resolved configuration (secrets masked)."""
    typer.echo("config: (not yet implemented)")
```

### Test Pattern
```python
# SOURCE: tests/test_cli.py:1-9
"""Tests for the CLI skeleton."""

from typer.testing import CliRunner

from shorts.cli import app

runner = CliRunner()
```

### Dependency Pinning
```toml
# SOURCE: pyproject.toml:9-14
dependencies = [
    "typer==0.15.4",
    "httpx==0.27.2",
    "pydantic==2.9.2",
    "python-dotenv==1.0.1",
]
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `src/shorts/config.py` | CREATE | BaseSettings config module with lazy validation |
| `.env.example` | CREATE | Document all configurable variables |
| `tests/test_config.py` | CREATE | Tests for config loading, masking, require() |
| `pyproject.toml` | UPDATE | Add pydantic-settings dependency |
| `src/shorts/cli.py` | UPDATE | Wire config command to use config module |

---

## Tasks

### Task 1: Add pydantic-settings to pyproject.toml

- **File**: `pyproject.toml`
- **Action**: UPDATE
- **Implement**: Add `"pydantic-settings==2.7.1"` to the `dependencies` list
- **Mirror**: `pyproject.toml:9-14` — follow existing pinned version format
- **Validate**: `pip install -e .[dev]`

### Task 2: Create config module

- **File**: `src/shorts/config.py`
- **Action**: CREATE
- **Implement**:
  - Import `BaseSettings` from `pydantic_settings`, `Optional` from typing, `typer`
  - Define `Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")`
  - Fields (all `Optional[str]` or `Optional[int]` with `None`/default):
    - `supadata_api_key: Optional[str] = None`
    - `openrouter_api_key: Optional[str] = None`
    - `default_model: str = "anthropic/claude-sonnet-4"`
    - `default_split: int = 50`
    - `default_clip_duration_min: int = 30`
    - `default_clip_duration_max: int = 60`
  - Define `require(settings, field_name) -> str` that reads `getattr(settings, field_name)`, raises `typer.BadParameter(f"Missing required config: {field_name.upper()}. Set it in .env")` if None, else returns the value
  - Define `mask(value: str) -> str` that returns first 3 chars + `"***"` if len > 3, else `"***"`
  - Module-level `settings = Settings()` singleton
- **Mirror**: `src/shorts/cli.py:1-3` — docstring + imports style
- **Validate**: `python -c "from shorts.config import settings"`

### Task 3: Wire config command in CLI

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**:
  - Replace the `config()` command body to:
    - Import `settings, mask` from `shorts.config`
    - Iterate `settings.model_fields` keys
    - For each field: get value via `getattr(settings, name)`
    - If field name contains "key" or "api" and value is not None: print masked
    - Else: print raw value
    - Format: `{NAME}: {value}`
- **Mirror**: `src/shorts/cli.py:30-32` — keep same decorator and docstring
- **Validate**: `shorts config`

### Task 4: Create .env.example

- **File**: `.env.example`
- **Action**: CREATE
- **Implement**: Document all env vars with placeholder values:
  ```
  SUPADATA_API_KEY=your_supadata_key_here
  OPENROUTER_API_KEY=your_openrouter_key_here
  DEFAULT_MODEL=anthropic/claude-sonnet-4
  DEFAULT_SPLIT=50
  DEFAULT_CLIP_DURATION_MIN=30
  DEFAULT_CLIP_DURATION_MAX=60
  ```
- **Validate**: File exists and is readable

### Task 5: Write tests

- **File**: `tests/test_config.py`
- **Action**: CREATE
- **Implement**:
  - `test_settings_loads_defaults()` — instantiate Settings() with no env, check default_model, default_split, default_clip_duration_min/max have expected defaults
  - `test_settings_loads_from_env(monkeypatch)` — set env vars, instantiate Settings(), verify values loaded
  - `test_require_raises_on_missing()` — settings with supadata_api_key=None, call require(settings, "supadata_api_key"), assert raises SystemExit (typer.BadParameter exits)
  - `test_require_returns_value(monkeypatch)` — set SUPADATA_API_KEY, call require(), assert returns the value
  - `test_mask_hides_secrets()` — mask("sk-abc123") returns "sk-***", mask("ab") returns "***"
  - `test_config_command_masks_keys(monkeypatch)` — set API keys in env, invoke `shorts config` via CliRunner, assert output contains masked values (not full keys)
  - `test_config_command_shows_defaults()` — invoke `shorts config`, assert DEFAULT_MODEL and DEFAULT_SPLIT appear in output
- **Mirror**: `tests/test_cli.py:1-9` — same imports and runner pattern
- **Validate**: `pytest tests/test_config.py -v`

---

## Validation

```bash
# Install with new dep
pip install -e .[dev]

# Run all tests
pytest -v

# Smoke test
shorts config
```

---

## End-to-End Tests

1. **Config prints defaults**: Run `shorts config` with no `.env` file → output shows `DEFAULT_MODEL: anthropic/claude-sonnet-4`, `DEFAULT_SPLIT: 50`, API keys show as `None`
2. **Config masks secrets**: Create a `.env` with `SUPADATA_API_KEY=sk-test123456`, run `shorts config` → output shows `SUPADATA_API_KEY: sk-***` (not the full key)
3. **Lazy validation works**: Run `shorts config` with missing keys → no error (just shows None). The error only happens when `require()` is called by a command that needs the key.

---

## Acceptance Criteria

- [ ] `pydantic-settings==2.7.1` added to pyproject.toml dependencies
- [ ] `src/shorts/config.py` exists with Settings class, require(), and mask()
- [ ] `shorts config` prints all settings with secrets masked
- [ ] `.env.example` documents all variables
- [ ] All tests pass (`pytest -v`)
- [ ] Lazy validation: missing keys don't error until require() is called
