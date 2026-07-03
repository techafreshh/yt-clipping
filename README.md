# YouTube Clipper

CLI tool that transforms long-form YouTube videos or local videos into vertical shorts (9:16, 1080×1920). Downloads the video, AI suggests highlight clips, adds TikTok-style captions, and exports separate vertical MP4s ready for YouTube Shorts, TikTok, and Reels.

## Features

- **Dual input sources** — YouTube URL or local video file path
- **AI highlight selection** — OpenRouter LLM suggests clip-worthy moments from transcript
- **Automatic transcript fetching** — Supadata API primary, yt-dlp subtitles fallback
- **9:16 vertical output** — Center-crops horizontal video, manual crop override in UI
- **TikTok-style captions** — Word-by-word highlighted subtitles burned into video
- **Silence removal** — Optional tighter pacing by removing silent gaps
- **Audio extraction** — Export WAV audio for podcast clips
- **Batch processing** — Multiple clips per source with graceful partial failure handling
- **Single-command pipeline** — Go from URL to finished shorts in one step
- **Web UI** — Visual editor for previewing, marking clips, and adjusting crop regions

## Prerequisites

- **Python 3.11+**
- **ffmpeg** on PATH (5.x+ recommended)
- **yt-dlp** for downloading YouTube videos (installed with the project)
- **Whisper** for local audio transcription (installed with the project)
- **Supadata API key** — for YouTube transcript fetching ([supadata.ai](https://supadata.ai))
- **OpenRouter API key** — for AI highlight suggestions ([openrouter.ai](https://openrouter.ai))

## Installation

```bash
git clone <repo-url>
cd yt-clipping
uv sync
```

For development (includes pytest):

```bash
uv sync --all-extras
```

## Configuration

Copy the example environment file and fill in your keys:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|----------|-------------|---------|
| `SUPADATA_API_KEY` | API key for transcript fetching | *(optional, yt-dlp/Whisper fallback)* |
| `OPENROUTER_API_KEY` | API key for AI highlight suggestions | *(required)* |
| `DEFAULT_MODEL` | OpenRouter model for suggestions | `anthropic/claude-sonnet-4` |

## Folder Conventions

```
yt-clipping/
├── raw/                          # Input videos
│   └── {name}.mp4
├── transcripts/                  # Cached transcripts
│   └── {name}.json
├── clips/                        # Clip specs (AI-generated or manual)
│   └── {name}.json
├── output/                       # Final vertical shorts
│   └── {name}/
│       └── {name}_short_01_{slug}.mp4
└── working/                      # Temporary files
```

## Quick Start

```bash
# 1. Download a YouTube video
uv run shorts download --youtube-url "https://youtube.com/watch?v=..."

# 2. Fetch transcript (or let the pipeline handle it)
uv run shorts transcript mypodcast --youtube-url "https://youtube.com/watch?v=..."

# 3. Get AI clip suggestions
uv run shorts suggest mypodcast

# 4. Cut and export vertical shorts
uv run shorts cut mypodcast --captions
```

Or run everything end-to-end:

```bash
uv run shorts run --youtube-url "https://youtube.com/watch?v=..." --captions
```

## Workflow: Local Video

```bash
# Use a local video file (name auto-derived from filename)
uv run shorts download --local-path /path/to/video.mp4

# Transcribe with Whisper (auto-transcribes local files)
uv run shorts transcript mypodcast --local-video /path/to/video.mp4

# Or run everything end-to-end
uv run shorts run --local-path /path/to/video.mp4 --captions
```

## CLI Reference

### `shorts download`

Download a YouTube video or copy a local video.

| Argument/Option | Description |
|-----------------|-------------|
| `NAME` | Source name identifier (auto-derived if omitted) |
| `--youtube-url` | YouTube video URL to download |
| `--local-path` | Local video file path to use |
| `--audio` | Also extract audio as WAV |

### `shorts transcript`

Fetch or load a transcript for a video.

| Argument/Option | Description |
|-----------------|-------------|
| `NAME` | Source name identifier (required) |
| `--youtube-url` | YouTube video URL to fetch transcript from |
| `--from-file` | Local transcript file path (JSON or .txt) |
| `--local-video` | Local video file to transcribe with Whisper |
| `--whisper-model` | Whisper model size (tiny/base/small/medium/large) |
| `--force` | Re-fetch even if cached |

### `shorts suggest`

AI-suggest clip-worthy highlights from a transcript.

| Argument/Option | Description |
|-----------------|-------------|
| `NAME` | Source name identifier (required) |
| `--model` | OpenRouter model to use |
| `--count` | Number of clips to suggest (default: 5) |

### `shorts cut`

Cut and export vertical shorts from clip specs.

| Argument/Option | Description |
|-----------------|-------------|
| `NAME` | Source name identifier (required) |
| `--fail-fast` | Stop on first clip failure |
| `--captions` | Burn TikTok-style captions |
| `--remove-silence` | Remove silent gaps for tighter pacing |
| `--audio` | Export audio alongside video clips |

### `shorts run`

Run the full pipeline end-to-end.

| Argument/Option | Description |
|-----------------|-------------|
| `NAME` | Source name identifier (auto-derived if omitted) |
| `--youtube-url` | YouTube URL for video + transcript |
| `--local-path` | Local video file path |
| `--model` | OpenRouter model |
| `--skip-suggest` | Use existing clips |
| `--fail-fast` | Stop on first clip failure |
| `--captions` | Burn TikTok-style captions |
| `--remove-silence` | Remove silent gaps |
| `--audio` | Extract audio for podcast clips |
| `--whisper-model` | Whisper model for local transcription |

### `shorts serve`

Start the local web UI server.

| Argument/Option | Description |
|-----------------|-------------|
| `--port` | Port to listen on (default: 8000) |
| `--host` | Host to bind to (default: 127.0.0.1) |

### `shorts config`

Print resolved configuration (secrets masked).

## Clip Spec Format

Each clip spec is a JSON array of objects:

```json
[
  {
    "start": "HH:MM:SS",
    "end": "HH:MM:SS",
    "slug": "kebab-case-name",
    "hook": "Optional one-line hook text",
    "crop": {"x": 0.1, "y": 0.2, "w": 0.8, "h": 0.6}
  }
]
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `start` | string | yes | Start timestamp (`HH:MM:SS`, `MM:SS`, or seconds) |
| `end` | string | yes | End timestamp (same formats) |
| `slug` | string | yes | Kebab-case identifier (`^[a-z0-9-]+$`) |
| `hook` | string | no | One-line hook/description for the clip |
| `crop` | object | no | Normalized crop region (0.0-1.0) for 9:16 reframing |

## Web UI

Start the editor with `shorts serve` and open http://127.0.0.1:8000.

Features:
- **Download tab** — Enter YouTube URL or local path to load video
- **AI Suggest tab** — Fetch transcript and generate clip suggestions
- **Manual tab** — Draw crop regions on video, mark in/out points
- **Crop drawing** — Click and drag on video to set custom crop region
- **Clip markers** — Timeline shows all clips with color-coded markers
- **Preview** — Play back specific clips before exporting
- **Cut All** — Export all clips with optional captions

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `ffmpeg: command not found` | Install ffmpeg and ensure it's on your PATH |
| `yt-dlp: command not found` | Install with `pip install yt-dlp` |
| Missing audio in output | Verify source video has an audio track |
| OpenRouter API errors | Check `OPENROUTER_API_KEY` in `.env`; verify model name is valid |
| Supadata API errors | Check `SUPADATA_API_KEY` in `.env`; transcript will fall back to yt-dlp |
| No cached transcript | Run `shorts transcript` before `shorts suggest` or `shorts cut --captions` |
| Crop not applied | Draw crop region on video in Manual tab, or use AI-suggested clips |

## Development

```bash
# Install with dev dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Project structure
src/shorts/
├── cli.py           # Typer CLI entry point
├── config.py        # Environment + settings
├── downloader.py    # yt-dlp video download + audio extract
├── transcript.py    # Supadata + yt-dlp + Whisper local transcription
├── highlights.py    # OpenRouter suggestions + clip model
├── cutter.py        # ffmpeg cut + silence removal + vertical crop
├── captions.py      # ASS subtitle generation
├── pipeline.py      # End-to-end orchestration
└── server.py        # FastAPI web UI server
```
