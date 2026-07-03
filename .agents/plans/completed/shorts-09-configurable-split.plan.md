# Plan: Configurable Layout Split

## Summary

SHORTS-09 is largely already implemented by SHORTS-08 (compositor). The compositor accepts a `split` parameter (20-80%), the CLI passes `--split` through, and `DEFAULT_SPLIT` in config provides the fallback. What remains is: (1) an explicit test for the `--split 70` acceptance criterion (1344px/576px), (2) a CLI-level validation that rejects out-of-range splits *before* calling the compositor (better UX with a clear error message), and (3) verifying the full test suite passes.

## User Story

As a creator
I want to configure the layout split between screen and camera
So that I can emphasize whichever view is more relevant for a given video

## Metadata

| Field | Value |
|-------|-------|
| Type | ENHANCEMENT |
| Complexity | LOW |
| Systems Affected | `src/shorts/cli.py`, `tests/test_compositor.py` |
| Jira Issue | SHORTS-09 |

---

## Patterns to Follow

### Naming
```python
# SOURCE: tests/test_compositor.py:42-60
def test_composite_clip_filter_60_40(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.compositor.OUTPUT_DIR", tmp_path)
    calls = []
    def capture_run(cmd, **kw):
        calls.append(cmd)
        return MagicMock()
    monkeypatch.setattr("shorts.compositor.subprocess.run", capture_run)
    clip = Clip(start="01:00", end="01:30", slug="clip")
    cut_result = CutResult(camera_path=Path("cam.mp4"), screen_path=Path("scr.mp4"))
    composite_clip("ep1", clip, cut_result, 1, split=60)
    filter_arg = calls[0][calls[0].index("-filter_complex") + 1]
    assert "scale=1080:1152" in filter_arg
    assert "scale=1080:768" in filter_arg
```

### Error Handling
```python
# SOURCE: src/shorts/cli.py:92-94
    if clips is None:
        typer.echo("Error: no clips found. Run 'shorts suggest' first.", err=True)
        raise typer.Exit(1)
```

### Tests
```python
# SOURCE: tests/test_compositor.py:131-148
def test_cli_cut_with_split(tmp_path, monkeypatch):
    monkeypatch.setattr("shorts.highlights.CLIPS_DIR", tmp_path)
    clips = [{"start": "01:00", "end": "01:30", "slug": "clip-one"}]
    (tmp_path / "ep1.json").write_text(json.dumps(clips))
    dummy_result = CutResult(camera_path=Path("a.mp4"), screen_path=Path("b.mp4"))
    monkeypatch.setattr("shorts.cutter.cut_clip", lambda name, clip: dummy_result)
    composite_calls = []
    def mock_composite(name, clip, result, index, split):
        composite_calls.append(split)
        return Path("output/ep1/ep1_short_01_clip-one.mp4")
    monkeypatch.setattr("shorts.compositor.composite_clip", mock_composite)
    result = runner.invoke(app, ["cut", "ep1", "--split", "60"])
    assert result.exit_code == 0
    assert composite_calls == [60]
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `src/shorts/cli.py` | UPDATE | Add early validation of `--split` range in `cut` command before processing |
| `tests/test_compositor.py` | UPDATE | Add test for `--split 70` (1344/576) acceptance criterion |

---

## Tasks

### Task 1: Add CLI-level split validation

- **File**: `src/shorts/cli.py`
- **Action**: UPDATE
- **Implement**: After resolving `use_split`, add a check: if `use_split` is outside 20-80, echo an error explaining the valid range and raise `typer.Exit(1)`. This gives a user-friendly message before any file I/O or ffmpeg calls.
- **Mirror**: `src/shorts/cli.py:92-94` — same pattern of echo + Exit(1)
- **Validate**: `pytest tests/test_compositor.py -k "invalid_split" -v`

### Task 2: Add explicit test for --split 70 acceptance criterion

- **File**: `tests/test_compositor.py`
- **Action**: UPDATE
- **Implement**: Add `test_composite_clip_filter_70_30` that calls `composite_clip` with `split=70` and asserts the filter contains `scale=1080:1344` (top) and `scale=1080:576` (bottom). This directly maps to the acceptance criterion: "Given `--split 70`, screen gets 1344px and camera gets 576px."
- **Mirror**: `tests/test_compositor.py:42-60` — follow `test_composite_clip_filter_60_40` pattern exactly
- **Validate**: `pytest tests/test_compositor.py::test_composite_clip_filter_70_30 -v`

### Task 3: Run full test suite

- **File**: N/A
- **Action**: VALIDATE
- **Implement**: Run `pytest` to confirm all tests pass (existing + new)
- **Validate**: `pytest`

---

## Validation

```bash
# Tests
pytest

# Import check
python -c "from shorts.compositor import composite_clip; from shorts.cli import app"
```

---

## Acceptance Criteria

- [ ] `--split 50` → screen and camera each get 960px (existing test confirms)
- [ ] `--split 70` → screen gets 1344px, camera gets 576px (new test)
- [ ] Split outside 20-80 → clear error at CLI level before ffmpeg runs
- [ ] `DEFAULT_SPLIT` from `.env` used when `--split` not passed (existing test confirms)
- [ ] All tests pass
