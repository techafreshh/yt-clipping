# Plan: Unit & Integration Test Suite

## Summary

Add a `tests/conftest.py` with session-scoped fixture mp4 generation via ffmpeg and an `ffmpeg` pytest marker for conditional skipping. Create `tests/test_integration.py` with real-ffmpeg integration tests that verify cutter output durations/audio, compositor output dimensions/codec, and a multi-clip pipeline run. Register the custom marker in `pyproject.toml`.

## User Story

As a developer
I want automated tests for each module (including integration tests with real ffmpeg)
So that I can refactor and extend the tool with confidence

## Metadata

| Field | Value |
|-------|-------|
| Type | ENHANCEMENT |
| Complexity | MEDIUM |
| Systems Affected | tests/, pyproject.toml |
| Jira Issue | SHORTS-14 |

---

## Patterns to Follow

### Test Structure
```python
# SOURCE: tests/test_cutter.py:60-80
def test_cut_clip_success(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "ep1_camera.mp4").write_bytes(b"fake")
    (raw / "ep1_screen.mp4").write_bytes(b"fake")

    working = tmp_path / "working"
    monkeypatch.setattr("shorts.cutter.RAW_DIR", raw)
    monkeypatch.setattr("shorts.cutter.WORKING_DIR", working)
    # ... test body
```

### Monkeypatching Module Constants
```python
# SOURCE: tests/test_transcript.py:30-35
def test_save_and_load_cached(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.transcript.TRANSCRIPTS_DIR", tmp_path)
```

### Subprocess Mocking
```python
# SOURCE: tests/test_cutter.py:20-27
def test_get_duration_success(monkeypatch):
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "45.5\n"
    monkeypatch.setattr("shorts.cutter.subprocess.run", lambda *a, **kw: mock_result)
```

### ffprobe Duration Check (from source)
```python
# SOURCE: src/shorts/cutter.py:18-24
def _get_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(result.stdout.strip())
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `tests/conftest.py` | CREATE | Shared fixtures: fixture mp4 generation, ffmpeg marker auto-skip |
| `tests/test_integration.py` | CREATE | Integration tests with real ffmpeg for cutter, compositor, pipeline |
| `pyproject.toml` | UPDATE | Add `[tool.pytest.ini_options]` with marker registration |

---

## Tasks

Execute in order. Each task is atomic and verifiable.

### Task 1: Register pytest markers in pyproject.toml

- **File**: `pyproject.toml`
- **Action**: UPDATE
- **Implement**: Add a `[tool.pytest.ini_options]` section with `markers = ["ffmpeg: requires ffmpeg on PATH"]`
- **Mirror**: Standard pytest marker registration pattern
- **Validate**: `pytest --markers` shows the `ffmpeg` marker without warnings

### Task 2: Create tests/conftest.py with fixture mp4 generation

- **File**: `tests/conftest.py`
- **Action**: CREATE
- **Implement**:
  1. Add a helper `_ffmpeg_available() -> bool` that runs `ffmpeg -version` and returns True/False
  2. Add `pytest_configure(config)` hook that registers the `ffmpeg` marker
  3. Add `pytest_collection_modifyitems(config, items)` hook that auto-skips tests marked `@pytest.mark.ffmpeg` when ffmpeg is not available
  4. Add a `session`-scoped fixture `fixture_camera_mp4(tmp_path_factory)` that generates a 2-second 320×240 mp4 with a sine-wave audio track via ffmpeg: `ffmpeg -y -f lavfi -i color=c=blue:s=320x240:d=2 -f lavfi -i sine=frequency=440:duration=2 -c:v libx264 -preset ultrafast -c:a aac -shortest <path>`
  5. Add a `session`-scoped fixture `fixture_screen_mp4(tmp_path_factory)` that generates a 2-second 640×480 mp4 with NO audio: `ffmpeg -y -f lavfi -i color=c=red:s=640x480:d=2 -c:v libx264 -preset ultrafast -an <path>`
  6. Add a `session`-scoped fixture `fixture_raw_dir(tmp_path_factory, fixture_camera_mp4, fixture_screen_mp4)` that creates a `raw/` directory with `test_camera.mp4` and `test_screen.mp4` symlinked/copied from the fixture files
  7. Add a fixture `fixture_transcript()` returning a `Transcript` with segments spanning 0–2s and word-level timestamps
- **Mirror**: `tests/test_transcript.py:30-35` for fixture patterns; `src/shorts/cutter.py:18-24` for ffprobe usage
- **Validate**: `pytest tests/conftest.py --collect-only` shows no errors; `pytest -m ffmpeg --collect-only` collects ffmpeg-marked tests

### Task 3: Create tests/test_integration.py with real ffmpeg tests

- **File**: `tests/test_integration.py`
- **Action**: CREATE
- **Implement**:
  All tests decorated with `@pytest.mark.ffmpeg`.

  **Test 1: `test_cutter_produces_correct_duration`**
  - Use `fixture_raw_dir`, monkeypatch `shorts.cutter.RAW_DIR` and `WORKING_DIR` to tmp dirs
  - Create a `Clip(start="00:00", end="00:01", slug="int-test")` (1-second clip from 2s source)
  - Call `cut_clip("test", clip)`
  - Assert both camera_path and screen_path exist
  - Run ffprobe on camera_path, assert duration is 1.0 ± 0.5s
  - Run ffprobe on screen_path, assert duration is 1.0 ± 0.5s

  **Test 2: `test_cutter_camera_has_audio_screen_has_none`**
  - Same setup as test 1
  - Run `ffprobe -v error -select_streams a -show_entries stream=codec_type -of csv=p=0` on camera_path → assert output contains "audio"
  - Run same on screen_path → assert output is empty (no audio stream)

  **Test 3: `test_compositor_output_dimensions`**
  - Use fixture_raw_dir, cut a clip, then call `composite_clip` with split=50
  - Run `ffprobe -v error -select_streams v -show_entries stream=width,height -of csv=p=0` on output
  - Assert width=1080, height=1920

  **Test 4: `test_compositor_output_codec`**
  - Same composite output as test 3
  - Run `ffprobe -v error -select_streams v -show_entries stream=codec_name -of csv=p=0`
  - Assert "h264"
  - Run `ffprobe -v error -select_streams a -show_entries stream=codec_name -of csv=p=0`
  - Assert "aac"

  **Test 5: `test_compositor_with_captions`**
  - Generate an ASS file via `generate_ass` using `fixture_transcript`
  - Composite with `subtitle_path` set
  - Assert output file exists and is larger than 0 bytes (subtitle filter applied without error)

  **Test 6: `test_pipeline_integration_multi_clip`**
  - Set up fixture_raw_dir, monkeypatch all directory constants (RAW_DIR, WORKING_DIR, OUTPUT_DIR, CLIPS_DIR, TRANSCRIPTS_DIR)
  - Save a transcript and 2 clips (one valid 0–1s, one valid 1–2s) to the tmp dirs
  - Call `run_pipeline` with `skip_suggest=True`
  - Assert result `success == 2`, `failed == 0`
  - Assert 2 output mp4 files exist in output dir

  **Test 7: `test_pipeline_integration_partial_failure`**
  - Same setup but one clip has `start="00:05"` (beyond 2s source duration)
  - Call `run_pipeline` with `skip_suggest=True`
  - Assert result `success == 1`, `failed == 1`
  - Assert 1 output mp4 exists

- **Mirror**: `tests/test_cutter.py:60-80` for directory setup; `tests/test_pipeline.py:30-50` for pipeline assertions; `src/shorts/cutter.py:18-24` for ffprobe commands
- **Validate**: `pytest tests/test_integration.py -m ffmpeg -v` (passes when ffmpeg available, skips otherwise)

---

## Validation

```bash
# All existing tests still pass
pytest tests/ -v --ignore=tests/test_integration.py

# Integration tests (requires ffmpeg on PATH)
pytest tests/test_integration.py -m ffmpeg -v

# Full suite
pytest -v

# No marker warnings
pytest --strict-markers --collect-only
```

---

## Acceptance Criteria

- [ ] `tests/conftest.py` exists with session-scoped fixture mp4 generation via ffmpeg
- [ ] `tests/test_integration.py` exists with ≥7 integration tests marked `@pytest.mark.ffmpeg`
- [ ] Integration tests verify output dimensions (1080×1920), audio presence, duration, and codec via ffprobe
- [ ] Pipeline integration test runs multi-clip batch with real files and verifies partial failure handling
- [ ] `pyproject.toml` has `[tool.pytest.ini_options]` with `markers` registered
- [ ] Tests auto-skip gracefully when ffmpeg is not on PATH
- [ ] `pytest` passes all tests (existing unit tests unaffected)
