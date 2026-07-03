# YouTube Shorts Repurposing Workflow — User Stories

> Generated from `.agents/PRDs/PRD.md`
> 14 stories across 4 implementation phases

---

## SHORTS-01: Project Scaffolding & CLI Skeleton

**Type**: Technical
**Jira Type**: Task
**Priority**: High
**Complexity**: Small
**Phase**: 1 — Foundation
**Labels**: `setup`, `cli`

### Description
As a developer, I want a properly structured Python project with CLI entry point, so that all subsequent features have a consistent foundation to build on.

### Acceptance Criteria
- [ ] Given a fresh clone, when I run `pip install -e .`, then the package installs without errors
- [ ] Given the package is installed, when I run `shorts --help`, then all subcommands (transcript, suggest, cut, run, config) are listed
- [ ] Given the project root, when I inspect the structure, then `src/shorts/`, `tests/`, `raw/`, `transcripts/`, `clips/`, `output/` directories exist
- [ ] Given `pyproject.toml`, when I check dependencies, then typer, httpx, pydantic, python-dotenv, and pytest are declared with pinned versions

### Technical Notes
- Use `pyproject.toml` with `[project.scripts]` to register `shorts` CLI entry point
- Typer app in `src/shorts/cli.py` with subcommand stubs
- Create `.gitkeep` in `raw/`, `transcripts/`, `clips/`, `output/`
- Python 3.11+ required

### Dependencies
- Blocked by: None
- Blocks: All other stories

---

## SHORTS-02: Configuration Loader

**Type**: Technical
**Jira Type**: Task
**Priority**: High
**Complexity**: Small
**Phase**: 1 — Foundation
**Labels**: `config`, `cli`

### Description
As a developer, I want a configuration module that loads API keys and defaults from `.env`, so that all modules can access settings consistently without hardcoding values.

### Acceptance Criteria
- [ ] Given a valid `.env` file, when config is loaded, then `SUPADATA_API_KEY`, `OPENROUTER_API_KEY`, `DEFAULT_MODEL`, `DEFAULT_SPLIT` are accessible
- [ ] Given a missing required key (e.g., no `SUPADATA_API_KEY`) and a command that needs it, when that command runs, then a clear error message names the missing variable
- [ ] Given the CLI, when I run `shorts config`, then all loaded settings are printed with API keys masked (e.g., `sk-...***`)
- [ ] Given `.env.example`, when I inspect it, then all configurable variables are documented with placeholder values

### Technical Notes
- Pydantic `BaseSettings` with `python-dotenv` for loading
- Lazy validation: only error on missing keys when the relevant subcommand is invoked
- Files: `src/shorts/config.py`, `.env.example`

### Dependencies
- Blocked by: SHORTS-01
- Blocks: SHORTS-03, SHORTS-05

---

## SHORTS-03: Transcript Fetching via Supadata API

**Type**: Feature
**Jira Type**: Story
**Priority**: High
**Complexity**: Medium
**Phase**: 1 — Foundation
**Labels**: `integration`, `supadata`, `transcript`

### Description
As a creator, I want to fetch my video's transcript automatically via its YouTube URL, so that I don't need to manually transcribe or export captions.

### Acceptance Criteria
- [ ] Given a valid YouTube URL and API key, when I run `shorts transcript episode12 --youtube-url <url>`, then `transcripts/episode12.json` is created with timestamped segments
- [ ] Given the transcript already exists in `transcripts/`, when I run the same command, then it uses the cached version (unless `--force` is passed)
- [ ] Given Supadata returns word-level timestamps, when the transcript is saved, then both `segments` and `words` arrays are present in the JSON
- [ ] Given Supadata is unreachable or returns an error, when the command runs, then a clear error message is shown with the HTTP status and suggestion to check the API key
- [ ] Given a retry scenario, when the first request fails with 5xx, then one retry is attempted with backoff

### Technical Notes
- `GET https://api.supadata.ai/v1/transcript?url={url}` with `x-api-key` header
- Pydantic models: `TranscriptSegment(start: float, end: float, text: str)`, `Transcript(segments: list, words: Optional[list])`
- Use httpx with timeout of 30s
- Files: `src/shorts/transcript.py`

### Dependencies
- Blocked by: SHORTS-02
- Blocks: SHORTS-05, SHORTS-08

---

## SHORTS-04: Local Transcript File Loader

**Type**: Feature
**Jira Type**: Story
**Priority**: Medium
**Complexity**: Small
**Phase**: 1 — Foundation
**Labels**: `transcript`

### Description
As a creator, I want to load a transcript from a local file, so that I can use my own transcription or a pre-existing caption file without needing the Supadata API.

### Acceptance Criteria
- [ ] Given a JSON file with `segments` array, when I run `shorts transcript episode12 --from-file transcript.json`, then `transcripts/episode12.json` is created in the standard format
- [ ] Given a plain text file (no timestamps), when loaded, then it is stored as a single segment spanning the full duration with a warning that timestamps are approximate
- [ ] Given an invalid file path, when the command runs, then a clear "file not found" error is shown

### Technical Notes
- Support two input formats: structured JSON (matching Transcript schema) and plain `.txt`
- Plain text fallback: single segment, no word-level timestamps
- Files: `src/shorts/transcript.py` (extend existing module)

### Dependencies
- Blocked by: SHORTS-01
- Blocks: SHORTS-05

---

## SHORTS-05: AI Highlight Suggestions via OpenRouter

**Type**: Feature
**Jira Type**: Story
**Priority**: High
**Complexity**: Medium
**Phase**: 2 — Core Pipeline
**Labels**: `ai`, `openrouter`, `highlights`

### Description
As a creator, I want AI to suggest clip-worthy moments from my transcript, so that I can discover engaging segments I might have missed.

### Acceptance Criteria
- [ ] Given a cached transcript, when I run `shorts suggest episode12 --model anthropic/claude-sonnet-4 --count 5`, then `clips/episode12.json` is created with 5 clip entries
- [ ] Given the LLM response, when parsed, then each clip has valid `start`, `end`, `slug`, and `hook` fields
- [ ] Given suggested clips, when validated, then all timestamps fall within the transcript's time range and each clip is between 15–90 seconds
- [ ] Given the LLM returns malformed JSON, when parsing fails, then one retry is attempted; if it fails again, the raw response is logged and a clear error is shown
- [ ] Given `--model` is not specified, when the command runs, then `DEFAULT_MODEL` from config is used

### Technical Notes
- OpenRouter endpoint: `POST https://openrouter.ai/api/v1/chat/completions`
- Use `response_format: { type: "json_object" }` for structured output
- Prompt should instruct: return JSON array of clips, each 30–60s, self-contained, with hook text
- Validate against Clip pydantic model; reject clips with end <= start
- Files: `src/shorts/highlights.py`

### Dependencies
- Blocked by: SHORTS-02, SHORTS-03 or SHORTS-04 (needs a transcript)
- Blocks: SHORTS-10

---

## SHORTS-06: Manual Clip Timestamps Parser

**Type**: Feature
**Jira Type**: Story
**Priority**: High
**Complexity**: Small
**Phase**: 1 — Foundation
**Labels**: `highlights`, `parser`

### Description
As a creator, I want to provide manual timestamps for clips, so that I can quickly produce shorts from moments I've already identified.

### Acceptance Criteria
- [ ] Given a valid `clips/episode12.json` with clip entries, when parsed, then each clip has `start`, `end`, `slug` (hook optional)
- [ ] Given timestamps in `HH:MM:SS`, `MM:SS`, or raw seconds format, when parsed, then all are correctly converted to seconds
- [ ] Given a clip where `end <= start`, when validated, then a descriptive error is raised naming the offending clip
- [ ] Given a clip duration outside 5–90s, when validated, then a warning is logged (not an error)
- [ ] Given a slug with unsafe filesystem characters, when validated, then an error is raised suggesting a safe alternative

### Technical Notes
- Pydantic model: `Clip(start: str, end: str, slug: str, hook: Optional[str])`
- Timestamp parsing: support `HH:MM:SS`, `MM:SS`, and float seconds
- Slug validation: `^[a-z0-9-]+$`
- Files: `src/shorts/highlights.py`

### Dependencies
- Blocked by: SHORTS-01
- Blocks: SHORTS-07

---

## SHORTS-07: Video Cutter (Dual-Track Extraction)

**Type**: Feature
**Jira Type**: Story
**Priority**: High
**Complexity**: Medium
**Phase**: 2 — Core Pipeline
**Labels**: `ffmpeg`, `video`, `core`

### Description
As a creator, I want both camera and screen tracks cut at the same timestamps, so that matching segments are ready for compositing.

### Acceptance Criteria
- [ ] Given a clip spec and source files in `raw/`, when cut, then two segment files are produced (camera with audio, screen without audio)
- [ ] Given the cut segments, when inspected with ffprobe, then durations match the requested range (±1 frame tolerance)
- [ ] Given the camera segment, when inspected, then it retains the original audio stream
- [ ] Given the screen segment, when inspected, then it has no audio stream
- [ ] Given source files don't exist in `raw/`, when the command runs, then a clear error names the expected file paths

### Technical Notes
- Use ffmpeg `-ss` (before input for speed) + `-to` for cutting
- Prefer `-c copy` (stream-copy) for speed; fall back to re-encode if keyframe alignment is poor
- Camera: keep audio (`-c:a copy`); Screen: strip audio (`-an`)
- Temp output to a working directory; cleaned up after compositing
- Files: `src/shorts/cutter.py`

### Dependencies
- Blocked by: SHORTS-06
- Blocks: SHORTS-08

---

## SHORTS-08: 9:16 Vertical Compositor

**Type**: Feature
**Jira Type**: Story
**Priority**: High
**Complexity**: Medium
**Phase**: 2 — Core Pipeline
**Labels**: `ffmpeg`, `video`, `core`

### Description
As a creator, I want my shorts to be vertical 9:16 with screen on top and camera on bottom, so that they're optimized for YouTube Shorts and TikTok without manual editing.

### Acceptance Criteria
- [ ] Given cut camera and screen segments, when composited with default split (50/50), then output is exactly 1080×1920
- [ ] Given `--split 60`, when composited, then screen occupies 60% (1152px) and camera 40% (768px) of the vertical space
- [ ] Given the output file, when inspected with ffprobe, then it is H.264 video + AAC audio, yuv420p pixel format
- [ ] Given source aspect ratios that don't perfectly fill their allocated space, when composited, then black bars pad the remaining area (no stretching)
- [ ] Given the output, when the audio is checked, then it comes from the camera track and is in sync

### Technical Notes
- ffmpeg filter chain: `[0:v]scale=1080:{top_h}:force_original_aspect_ratio=decrease,pad=1080:{top_h}[top]; [1:v]scale=1080:{bot_h}:force_original_aspect_ratio=decrease,pad=1080:{bot_h}[bot]; [top][bot]vstack`
- Map audio from camera input: `-map 1:a`
- Output naming: `output/{source_name}/{source_name}_short_{NN}_{slug}.mp4`
- Files: `src/shorts/compositor.py`

### Dependencies
- Blocked by: SHORTS-07
- Blocks: SHORTS-09, SHORTS-10

---

## SHORTS-09: Configurable Layout Split

**Type**: Feature
**Jira Type**: Story
**Priority**: Medium
**Complexity**: Small
**Phase**: 2 — Core Pipeline
**Labels**: `video`, `config`

### Description
As a creator, I want to configure the layout split between screen and camera, so that I can emphasize whichever view is more relevant for a given video.

### Acceptance Criteria
- [ ] Given `--split 50` (default), when composited, then screen and camera each get 960px of the 1920px height
- [ ] Given `--split 70`, when composited, then screen gets 1344px and camera gets 576px
- [ ] Given a split value outside 20–80, when the command runs, then an error is raised explaining the valid range
- [ ] Given `DEFAULT_SPLIT` is set in `.env`, when `--split` is not passed, then the env value is used

### Technical Notes
- Split percentage refers to screen (top) portion; camera (bottom) gets the remainder
- Enforce min 20%, max 80% to prevent unusable layouts
- Integrate into compositor filter chain calculation
- Files: `src/shorts/compositor.py`, `src/shorts/config.py`

### Dependencies
- Blocked by: SHORTS-08
- Blocks: None

---

## SHORTS-10: End-to-End Pipeline Command

**Type**: Feature
**Jira Type**: Story
**Priority**: High
**Complexity**: Medium
**Phase**: 3 — Polish
**Labels**: `pipeline`, `cli`

### Description
As a creator, I want to run the entire pipeline end-to-end with a single command, so that I can go from raw recordings to finished shorts with minimal steps.

### Acceptance Criteria
- [ ] Given source files in `raw/` and a YouTube URL, when I run `shorts run episode12 --youtube-url <url>`, then transcript is fetched, highlights are suggested, and shorts are produced in `output/episode12/`
- [ ] Given `--captions` flag, when the pipeline runs, then captions are burned into the output
- [ ] Given `--split` and `--model` flags, when the pipeline runs, then those values are passed through to the relevant stages
- [ ] Given progress logging, when the pipeline runs, then each step is logged (e.g., `[1/3] Fetching transcript...`, `[2/3] Suggesting highlights...`, `[3/3] Cutting clip 1/5: best-tip...`)
- [ ] Given a pre-existing `clips/episode12.json`, when `--skip-suggest` is passed, then the existing clips are used without calling the LLM

### Technical Notes
- Orchestration in `src/shorts/pipeline.py`
- CLI wiring in `src/shorts/cli.py` under `shorts run`
- Reuse existing modules: transcript.py → highlights.py → cutter.py → compositor.py
- Files: `src/shorts/pipeline.py`, `src/shorts/cli.py`

### Dependencies
- Blocked by: SHORTS-05, SHORTS-08
- Blocks: SHORTS-11

---

## SHORTS-11: Batch Processing & Error Handling

**Type**: Feature
**Jira Type**: Story
**Priority**: Medium
**Complexity**: Small
**Phase**: 3 — Polish
**Labels**: `pipeline`, `reliability`

### Description
As a creator, I want batch processing to continue even if individual clips fail, so that one bad timestamp doesn't waste the entire run.

### Acceptance Criteria
- [ ] Given 5 clips where clip 3 has an invalid timestamp, when the batch runs, then clips 1, 2, 4, 5 are produced and clip 3 is skipped with an error logged
- [ ] Given partial failures, when the batch completes, then a summary is printed: `4/5 clips succeeded, 1 failed`
- [ ] Given any clip failure, when the batch exits, then the exit code is non-zero (e.g., 1)
- [ ] Given `--fail-fast` flag, when a clip fails, then the batch stops immediately

### Technical Notes
- Try/except around each clip in the batch loop
- Collect errors in a list; print summary at end
- Exit code: 0 if all succeed, 1 if any fail
- Files: `src/shorts/pipeline.py`

### Dependencies
- Blocked by: SHORTS-10
- Blocks: None

---

## SHORTS-12: TikTok-Style Caption Burning

**Type**: Feature
**Jira Type**: Story
**Priority**: Medium
**Complexity**: Large
**Phase**: 3 — Polish
**Labels**: `captions`, `ffmpeg`, `video`

### Description
As a creator, I want optional TikTok-style captions burned into my shorts, so that I can improve retention without using a separate captioning tool.

### Acceptance Criteria
- [ ] Given `--captions` flag and a transcript with word-level timestamps, when the short is produced, then captions appear with word-by-word highlighting synced to speech
- [ ] Given a transcript with only segment-level timestamps (no words), when `--captions` is used, then segment-level subtitles are shown with a warning that word-highlight is unavailable
- [ ] Given the caption style, when inspected visually, then text is bold white with black stroke, centered horizontally, positioned in the middle third of the frame
- [ ] Given `--captions` is NOT passed, when the short is produced, then no captions are present
- [ ] Given the captioned output, when file size is compared to non-captioned, then it is larger (confirming the subtitle filter was applied)

### Technical Notes
- Generate ASS subtitle file from transcript word timestamps within clip time range
- ASS styling: `\fn Arial,\fs 48,\bord 4,\c&HFFFFFF&,\3c&H000000&` with `\kf` for word-by-word karaoke highlight
- Apply via ffmpeg `subtitles` filter on the composited output
- Fallback: segment-level uses `\fad` timing per segment
- Files: `src/shorts/captions.py`, extend `src/shorts/compositor.py`

### Dependencies
- Blocked by: SHORTS-08, SHORTS-03 (needs transcript with timestamps)
- Blocks: None

---

## SHORTS-13: README & Documentation

**Type**: Technical
**Jira Type**: Task
**Priority**: Medium
**Complexity**: Small
**Phase**: 4 — Documentation
**Labels**: `docs`

### Description
As a developer, I want comprehensive documentation, so that I (or anyone else) can set up and use the tool without external guidance.

### Acceptance Criteria
- [ ] Given the README, when read, then it covers: prerequisites (ffmpeg, Python 3.11+), installation, `.env` setup, folder conventions, full workflow walkthrough (manual + AI mode), CLI reference
- [ ] Given `.env.example`, when copied to `.env` and filled in, then the tool runs without config errors
- [ ] Given `clips/example.json`, when used with test videos, then it demonstrates the expected format
- [ ] Given `shorts --help`, when run, then all documented subcommands match the README

### Technical Notes
- Include troubleshooting section: sync mismatch, missing audio, OpenRouter errors, ffmpeg not found
- Files: `README.md`, `.env.example`, `clips/example.json`

### Dependencies
- Blocked by: SHORTS-10
- Blocks: None

---

## SHORTS-14: Unit & Integration Test Suite

**Type**: Technical
**Jira Type**: Task
**Priority**: Medium
**Complexity**: Medium
**Phase**: 1–3 (ongoing)
**Labels**: `testing`

### Description
As a developer, I want automated tests for each module, so that I can refactor and extend the tool with confidence.

### Acceptance Criteria
- [ ] Given the test suite, when I run `pytest`, then all tests pass
- [ ] Given `config.py`, when tested, then loading from `.env`, missing key errors, and masking are covered
- [ ] Given `transcript.py`, when tested, then Supadata HTTP call is mocked and both JSON and plain text loading are verified
- [ ] Given `highlights.py`, when tested, then manual parsing (valid, invalid timestamps, bad slugs) and OpenRouter mock (valid response, malformed retry) are covered
- [ ] Given `cutter.py` and `compositor.py`, when tested with fixture mp4 files, then output dimensions, audio presence, and duration are verified via ffprobe
- [ ] Given the pipeline, when tested end-to-end with fixtures, then a multi-clip batch produces correct outputs and handles one deliberate failure gracefully

### Technical Notes
- Use pytest with `tmp_path` for isolated file I/O
- Mock HTTP calls with `respx` or `pytest-httpx`
- Small fixture mp4s (1–2s, low-res) for video tests — generate with ffmpeg in a conftest
- Files: `tests/test_config.py`, `tests/test_transcript.py`, `tests/test_highlights.py`, `tests/test_cutter.py`, `tests/test_compositor.py`, `tests/test_pipeline.py`, `tests/conftest.py`

### Dependencies
- Blocked by: SHORTS-01
- Blocks: None (runs in parallel with feature work)

---

## Story Dependency Graph

```
SHORTS-01 (Scaffolding)
├── SHORTS-02 (Config)
│   ├── SHORTS-03 (Supadata Transcript)
│   │   ├── SHORTS-05 (AI Highlights)
│   │   └── SHORTS-12 (Captions)
│   └── SHORTS-05 (AI Highlights)
├── SHORTS-04 (Local Transcript)
│   └── SHORTS-05 (AI Highlights)
├── SHORTS-06 (Manual Clips Parser)
│   └── SHORTS-07 (Video Cutter)
│       └── SHORTS-08 (Compositor)
│           ├── SHORTS-09 (Configurable Split)
│           ├── SHORTS-10 (E2E Pipeline)
│           │   ├── SHORTS-11 (Batch Error Handling)
│           │   └── SHORTS-13 (README)
│           └── SHORTS-12 (Captions)
└── SHORTS-14 (Tests) — parallel
```

---

## Phase Summary

| Phase | Stories | Focus |
|-------|---------|-------|
| 1 — Foundation | SHORTS-01, 02, 03, 04, 06 | Project setup, config, transcript, manual clips |
| 2 — Core Pipeline | SHORTS-05, 07, 08, 09 | AI highlights, cutting, compositing |
| 3 — Polish | SHORTS-10, 11, 12 | Pipeline orchestration, captions, error handling |
| 4 — Documentation | SHORTS-13 | README, examples |
| Ongoing | SHORTS-14 | Testing |
