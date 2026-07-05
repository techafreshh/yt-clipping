#!/bin/bash
# Delete video files older than CLEANUP_MAX_AGE_DAYS (default: 7)
# Runs hourly via cron inside the container

set -euo pipefail

MAX_AGE="${CLEANUP_MAX_AGE_DAYS:-7}"

echo "[$(date -Iseconds)] Cleanup: deleting .mp4 files older than ${MAX_AGE} days"

# Delete old mp4 files from raw/ and output/
find /app/raw/ /app/output/ -name "*.mp4" -mtime +"${MAX_AGE}" -delete 2>/dev/null || true

# Remove empty directories left behind
find /app/raw/ /app/output/ -type d -empty -delete 2>/dev/null || true

# Always wipe working/ — these are temp files from cutting
rm -rf /app/working/*

echo "[$(date -Iseconds)] Cleanup complete"
