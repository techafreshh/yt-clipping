# Plan: Local Web UI for Shorts Editor

## Summary

Add a local browser-based UI (FastAPI + vanilla HTML/JS) that lets the user load screen/camera footage, play and scrub video to select clip timestamps, draw crop regions on each source, adjust the split ratio, and trigger the cut/composite pipeline with one click. The server runs locally via `shorts serve` and reuses all existing pipeline modules.

## User Story

As a content creator
I want a local browser UI to visually select clip timestamps, crop regions, and split ratio on my footage
So that I can produce shorts faster without hand-editing JSON files or memorizing CLI flags

## Metadata

| Field | Value |
|-------|-------|
| Type | NEW_CAPABILITY |
| Complexity | HIGH |
| Systems Affected | cli, compositor, highlights (Clip model), pyproject.toml, new server + static UI |
| Jira Issue | N/A |

---

## Patterns to Follow

### Naming
```python
# SOURCE: src/shorts/cutter.py:1-10
"""Video cutter — dual-track ffmpeg extraction."""
from pathlib import Path
RAW_DIR = Path("raw")
WORKING_DIR = Path("working")
```
Module-level Path constants, snake_case functions, docstring at top.

### Error Handling
```python
# SOURCE: src/shorts/compositor.py:14-15
if not 20 <= split <= 80:
    raise ValueError(f"Split must be 20-80, got {split}")
```
```python
# SOURCE: src/shorts/cutter.py:28-29
if result.returncode != 0:
    raise RuntimeError(f"ffprobe failed for {path}: {result.stderr}")
```
ValueError for validation, RuntimeError for subprocess/external failures, FileNotFoundError for missing files.

### Types
```python
# SOURCE: src/shorts/highlights.py:18-27
class Clip(BaseModel):
    start: str
    end: str
    slug: str
    hook: Optional[str] = None
```
```python
# SOURCE: src/shorts/cutter.py:13-15
class CutResult(BaseModel):
    camera_path: Path
    screen_path: Path
```
Pydantic BaseModel for all data structures. Optional fields with None defaults for backward compat.

### Tests
```python
# SOURCE: tests/test_compositor.py:20-30
def test_composite_clip_success(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.compositor.OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("shorts.compositor.subprocess.run", lambda *a, **kw: MagicMock())
    clip = Clip(start="01:00", end="01:30", slug="test-clip")
    cut_result = CutResult(camera_path=Path("cam.mp4"), screen_path=Path("scr.mp4"))
    result = composite_clip("ep1", clip, cut_result, 1)
    assert result == tmp_path / "ep1" / "ep1_short_01_test-clip.mp4"
```
monkeypatch for subprocess mocking, tmp_path for file isolation, CliRunner for CLI tests.

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `pyproject.toml` | UPDATE | Add fastapi, uvicorn[standard] dependencies |
| `src/shorts/highlights.py` | UPDATE | Extend Clip model with optional crop_screen, crop_camera, split fields |
| `src/shorts/compositor.py` | UPDATE | Accept crop coordinates and apply in ffmpeg filter |
| `src/shorts/server.py` | CREATE | FastAPI app: video serving, clip CRUD, cut trigger with SSE |
| `src/shorts/static/index.html` | CREATE | Single-page UI: video players, timeline, crop editor, clip list |
| `src/shorts/cli.py` | UPDATE | Add `shorts serve` command |
| `tests/test_server.py` | CREATE | API endpoint tests |
| `tests/test_compositor.py` | UPDATE | Tests for crop parameter handling |

---

## Tasks

Execute in order. Each task is atomic and verifiable.

### Task 1: Add dependencies

- **File**: `pyproject.toml`
- **Action**: UPDATE
- **Implement**: Add `fastapi==0.115.6` and `uvicorn[standard]==0.34.0` to the `dependencies` list.
- **Mirror**: existing pinned deps pattern in `pyproject.toml:8-13`
- **Validate**: `pip install -e .` succeeds

### Task 2: Extend Clip model with crop and split fields

- **File**: `src/shorts/highlights.py`
- **Action**: UPDATE
- **Implement**: Add a `CropRegion` model with fields `x: float`, `y: float`, `w: float`, `h: float` (all 0.0-1.0 normalized). Add optional fields to `Clip`: `crop_screen: Optional[CropRegion] = None`, `crop_camera: Optional[CropRegion] = None`, `split: Optional[int] = None`. These are Optional so existing JSON files remain valid.
- **Mirror**: `src/shorts/highlights.py:18-27` — Clip model pattern
- **Validate**: `python -c "from shorts.highlights import Clip; Clip(start='01:00', end='02:00', slug='test')"` — existing usage still works. `python -c "from shorts.highlights import Clip, CropRegion; Clip(start='01:00', end='02:00', slug='test', crop_screen=CropRegion(x=0.1, y=0.1, w=0.8, h=0.8))"` — new usage works.

### Task 3: Add crop support to compositor

- **File**: `src/shorts/compositor.py`
- **Action**: UPDATE
- **Implement**: Add optional `crop_screen` and `crop_camera` parameters (each a dict with `x, y, w, h` as 0-1 floats or None). When provided, use ffprobe to get source dimensions, then compute pixel crop values (`crop=out_w:out_h:x:y`) and insert before the scale filter. When None, keep existing behavior (scale + center-crop). Add a helper `_probe_dimensions(path: Path) -> tuple[int, int]` to get source width/height.
- **Mirror**: `src/shorts/compositor.py:13-58` — existing filter_complex construction
- **Validate**: `pytest tests/test_compositor.py` passes (existing tests unchanged). New tests verify crop filter is included in ffmpeg command when crop params provided.

### Task 4: Create FastAPI server with video serving

- **File**: `src/shorts/server.py`
- **Action**: CREATE
- **Implement**:
  - Module docstring: `"""Local web UI server for the shorts editor."""`
  - Module-level constant: `RAW_DIR = Path("raw")`
  - `create_app() -> FastAPI` factory function
  - `GET /api/health` — returns `{"status": "ok"}`
  - `GET /api/videos/{name}/{track}` — serves `raw/{name}_{track}.mp4` with HTTP Range request support (206 Partial Content). `track` is "screen" or "camera".
  - `GET /` — serves `static/index.html`
  - Mount static files from the `static/` directory within the package
- **Mirror**: `src/shorts/cutter.py:1-10` for module structure; HTTP range pattern from standard FastAPI streaming response
- **Validate**: `python -c "from shorts.server import create_app; app = create_app()"` succeeds

### Task 5: Add clip CRUD API endpoints

- **File**: `src/shorts/server.py`
- **Action**: UPDATE
- **Implement**:
  - `GET /api/clips/{name}` — returns clip list as JSON (calls `load_clips`)
  - `POST /api/clips/{name}` — accepts clip JSON body, appends to list, saves (calls `save_clips`)
  - `PUT /api/clips/{name}/{index}` — updates clip at index
  - `DELETE /api/clips/{name}/{index}` — removes clip at index
  - Use Pydantic request models matching the extended Clip schema
  - Return 404 when no clips file exists on GET, return empty list
- **Mirror**: `src/shorts/highlights.py:88-100` — load_clips/save_clips pattern
- **Validate**: `pytest tests/test_server.py` — CRUD operations work correctly

### Task 6: Add cut/composite endpoint with SSE progress

- **File**: `src/shorts/server.py`
- **Action**: UPDATE
- **Implement**:
  - `POST /api/cut/{name}` — triggers cut+composite for all clips. Accepts optional `captions: bool` query param.
  - Uses `StreamingResponse` with `text/event-stream` media type for SSE.
  - For each clip: emit SSE event `{"clip": slug, "status": "cutting", "index": i, "total": n}`, then `{"clip": slug, "status": "done"}` or `{"clip": slug, "status": "failed", "error": msg}`.
  - Calls `cut_clip` and `composite_clip` directly (not `run_pipeline`) to have per-clip control.
  - Passes crop coordinates from clip spec to compositor.
  - Final SSE event: `{"status": "complete", "success": n, "failed": m}`.
- **Mirror**: `src/shorts/pipeline.py:40-80` — cut/composite loop pattern
- **Validate**: `pytest tests/test_server.py` — cut endpoint returns SSE events

### Task 7: Add `shorts serve` CLI command

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**: Add a `serve` command with optional `--port` (default 8000) and `--host` (default "127.0.0.1") options. Imports `uvicorn` and `create_app` from `shorts.server`, runs `uvicorn.run(app, host=host, port=port)`. Print a message with the URL before starting.
- **Mirror**: `src/shorts/cli.py:1-10` — existing command pattern
- **Validate**: `shorts serve --help` shows the command. `shorts --help` lists `serve`.

### Task 8: Create static HTML/JS UI — video playback and timeline

- **File**: `src/shorts/static/index.html`
- **Action**: CREATE
- **Implement**:
  - Single HTML file with embedded CSS and JS (no build step)
  - Layout: header with project name input + "Load" button; main area with two `<video>` elements (screen left, camera right); shared timeline/seekbar below videos; clip list sidebar on the right
  - On "Load": fetch videos from `/api/videos/{name}/screen` and `/api/videos/{name}/camera`, set as `<video>` src
  - Synced playback: play/pause/seek controls that keep both videos in sync (timeupdate listener syncs the follower)
  - Timeline bar: shows video duration, current position indicator, click-to-seek
  - "Mark In" / "Mark Out" buttons that capture current time and prompt for slug
  - Clip list: shows all clips with start/end/slug, click to seek, delete button
  - Clips saved via `POST /api/clips/{name}` on creation, `DELETE` on removal
  - On page load with name, fetch existing clips via `GET /api/clips/{name}`
- **Mirror**: N/A (new file, vanilla HTML/JS)
- **Validate**: Manual — open `http://localhost:8000`, load a project, videos play in sync, can mark clips

### Task 9: Add crop region editor to UI

- **File**: `src/shorts/static/index.html`
- **Action**: UPDATE
- **Implement**:
  - Canvas overlay on each `<video>` element (positioned absolutely over the video)
  - Mouse events: mousedown starts crop, mousemove draws rectangle, mouseup finalizes
  - Draw semi-transparent rectangle with border showing the crop region
  - Store crop as normalized coordinates (0-1 relative to video dimensions)
  - "Global crop" mode when no clip is selected; "Per-clip crop" when a clip is active in the list
  - Visual indicator (badge/label) showing "Global" vs clip slug
  - Reset crop button to clear back to full frame
  - On crop change: `PUT /api/clips/{name}/{index}` to persist per-clip crop, or store global in localStorage
- **Mirror**: N/A (canvas interaction, vanilla JS)
- **Validate**: Manual — draw crop on screen video, switch clips, verify per-clip crops persist

### Task 10: Add split ratio control and cut button to UI

- **File**: `src/shorts/static/index.html`
- **Action**: UPDATE
- **Implement**:
  - Range slider (20-80) for split ratio with numeric display
  - Mini preview panel: 9:16 rectangle showing the split line position with "Screen" / "Camera" labels
  - Global default split + per-clip override (same pattern as crop)
  - "Cut All" button that POSTs to `/api/cut/{name}` and reads SSE response
  - Progress display: per-clip status indicators (pending → cutting → done/failed)
  - On completion: show summary and link to output folder
- **Mirror**: N/A (vanilla JS)
- **Validate**: Manual — adjust split, click Cut All, see progress, verify output files created

### Task 11: Write server tests

- **File**: `tests/test_server.py`
- **Action**: CREATE
- **Implement**:
  - Use `httpx.AsyncClient` with FastAPI's `TestClient` (or `from starlette.testclient import TestClient`)
  - `test_health` — GET /api/health returns 200
  - `test_video_serve_range` — GET /api/videos/{name}/screen with Range header returns 206 with correct Content-Range
  - `test_video_serve_missing` — GET /api/videos/nonexistent/screen returns 404
  - `test_clips_crud` — create, read, update, delete clips via API, verify JSON file on disk
  - `test_clips_with_crop` — create clip with crop_screen, read back, verify fields
  - `test_cut_endpoint` — mock subprocess.run, POST /api/cut/{name}, verify SSE events emitted
  - Use tmp_path + monkeypatch to isolate RAW_DIR, CLIPS_DIR, OUTPUT_DIR
- **Mirror**: `tests/test_compositor.py:20-30` — monkeypatch + tmp_path pattern
- **Validate**: `pytest tests/test_server.py` passes

### Task 12: Add compositor crop tests

- **File**: `tests/test_compositor.py`
- **Action**: UPDATE
- **Implement**:
  - `test_composite_clip_with_crop_screen` — verify ffmpeg command includes crop filter with correct pixel values when crop_screen is provided
  - `test_composite_clip_with_crop_both` — verify both screen and camera crop filters present
  - `test_composite_clip_no_crop_unchanged` — verify existing behavior when no crop provided (regression)
  - Mock `_probe_dimensions` to return known values, capture subprocess.run args
- **Mirror**: `tests/test_compositor.py:34-50` — capture_run pattern
- **Validate**: `pytest tests/test_compositor.py` passes

---

## Validation

```bash
# Install with new deps
pip install -e .

# Type check (if mypy configured)
# N/A — project doesn't use mypy currently

# Lint
ruff check src/ tests/

# Tests
pytest

# Manual smoke test
shorts serve
# Open http://localhost:8000, load sk1, verify playback + clip creation + cut
```

---

## Acceptance Criteria

- [ ] `shorts serve` starts a local server on port 8000
- [ ] Browser UI loads and plays both screen/camera videos in sync
- [ ] Can mark start/end timestamps from video playback position
- [ ] Can draw crop regions on each video source
- [ ] Crop supports global default + per-clip override
- [ ] Split ratio slider works (20-80) with visual preview
- [ ] "Cut All" triggers pipeline and shows real-time progress via SSE
- [ ] Output files are produced correctly with custom crop applied
- [ ] Existing CLI workflow (`shorts cut`) still works unchanged
- [ ] Existing clip JSON files load without errors (backward compatible)
- [ ] All tests pass
