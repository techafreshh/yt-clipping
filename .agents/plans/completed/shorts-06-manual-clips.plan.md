# Plan: SHORTS-06 Manual Clip Timestamps Parser

## Summary

Fix two gaps in the existing manual clip parser to fully satisfy SHORTS-06 acceptance criteria: (1) change the duration warning threshold from 15–90s to 5–90s, and (2) enhance the slug validator to suggest a safe alternative when rejecting invalid slugs. Both changes are in `highlights.py` with corresponding test updates.

## User Story

As a creator
I want to provide manual timestamps for clips
So that I can quickly produce shorts from moments I've already identified

## Metadata

| Field | Value |
|-------|-------|
| Type | ENHANCEMENT |
| Complexity | LOW |
| Systems Affected | highlights, tests |
| Jira Issue | SHORTS-06 |

---

## Patterns to Follow

### Naming
```python
# SOURCE: src/shorts/highlights.py:27-30
@field_validator("slug")
@classmethod
def slug_format(cls, v: str) -> str:
    if not re.match(r"^[a-z0-9-]+$", v):
        raise ValueError("slug must match ^[a-z0-9-]+$")
    return v
```

### Error Handling
```python
# SOURCE: src/shorts/highlights.py:49-51
if end <= start:
    raise ValueError(f"Clip '{clip.slug}': end ({clip.end}) <= start ({clip.start})")
```

### Warning Pattern
```python
# SOURCE: src/shorts/highlights.py:54-55
if duration < 15 or duration > 90:
    warnings.warn(f"Clip '{clip.slug}' duration {duration:.1f}s outside 15-90s range", stacklevel=2)
```

### Tests
```python
# SOURCE: tests/test_highlights.py:57-58
def test_clip_invalid_slug():
    with pytest.raises(ValueError, match="slug must match"):
        Clip(start="01:00", end="01:45", slug="Bad Slug!")
```

```python
# SOURCE: tests/test_highlights.py:80-82
def test_validate_clips_warns_outside_range():
    clips = [Clip(start="00:00", end="00:10", slug="short-clip")]
    with pytest.warns(UserWarning, match="outside 15-90s"):
        validate_clips(clips, 300.0)
```

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `src/shorts/highlights.py` | UPDATE | Fix duration threshold (5s) and add safe slug suggestion |
| `tests/test_highlights.py` | UPDATE | Update warning match string and add slug suggestion test |

---

## Tasks

Execute in order. Each task is atomic and verifiable.

### Task 1: Fix duration warning threshold

- **File**: `src/shorts/highlights.py`
- **Action**: UPDATE
- **Implement**: On line 54, change `duration < 15` to `duration < 5`. On line 55, change the warning message from `"outside 15-90s range"` to `"outside 5-90s range"`.
- **Mirror**: `src/shorts/highlights.py:54-55` — same pattern, just different threshold
- **Validate**: `pytest tests/test_highlights.py::test_validate_clips_warns_outside_range -x` (will fail until Task 3)

### Task 2: Enhance slug validator to suggest safe alternative

- **File**: `src/shorts/highlights.py`
- **Action**: UPDATE
- **Implement**: In the `slug_format` validator (lines 27-30), when the slug doesn't match, generate a safe alternative using `re.sub(r"[^a-z0-9-]+", "-", v.lower()).strip("-")` and include it in the error message: `f"slug must match ^[a-z0-9-]+$; try '{safe}' instead"`.
- **Mirror**: `src/shorts/highlights.py:27-30` — extend existing validator
- **Validate**: `pytest tests/test_highlights.py::test_clip_invalid_slug -x` (will fail until Task 4)

### Task 3: Update test for new warning threshold

- **File**: `tests/test_highlights.py`
- **Action**: UPDATE
- **Implement**: On line 82, change `match="outside 15-90s"` to `match="outside 5-90s"`.
- **Mirror**: `tests/test_highlights.py:80-82`
- **Validate**: `pytest tests/test_highlights.py::test_validate_clips_warns_outside_range -x`

### Task 4: Add test for slug suggestion in error message

- **File**: `tests/test_highlights.py`
- **Action**: UPDATE
- **Implement**: Add a new test after `test_clip_invalid_slug` that verifies the error message includes a suggested alternative:
  ```python
  def test_clip_invalid_slug_suggests_alternative():
      with pytest.raises(ValueError, match="try 'bad-slug' instead"):
          Clip(start="01:00", end="01:45", slug="Bad Slug!")
  ```
- **Mirror**: `tests/test_highlights.py:57-58` — same pytest.raises pattern
- **Validate**: `pytest tests/test_highlights.py::test_clip_invalid_slug_suggests_alternative -x`

---

## Validation

```bash
# Lint
ruff check src/shorts/highlights.py

# Tests — full highlights suite
pytest tests/test_highlights.py -v

# All tests pass
pytest
```

---

## Acceptance Criteria

- [ ] AC1: Valid clips JSON parsed with start, end, slug (hook optional) — already passing
- [ ] AC2: HH:MM:SS, MM:SS, raw seconds all parsed correctly — already passing
- [ ] AC3: end <= start raises descriptive ValueError naming the clip — already passing
- [ ] AC4: Duration outside 5–90s logs a warning (not error) — **Task 1 + Task 3**
- [ ] AC5: Invalid slug raises error suggesting a safe alternative — **Task 2 + Task 4**
- [ ] All existing tests still pass
- [ ] Lint passes
