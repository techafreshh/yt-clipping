#!/bin/bash
# Container entrypoint: starts cron daemon + uvicorn
set -euo pipefail

echo "Shorts: Cleaning working directory on startup..."
rm -rf /app/working/*

echo "Shorts: Setting up hourly cron job (cleanup every hour)..."
CLEANUP_MAX_AGE_DAYS="${CLEANUP_MAX_AGE_DAYS:-7}"
echo "0 * * * * CLEANUP_MAX_AGE_DAYS=${CLEANUP_MAX_AGE_DAYS} /bin/bash /app/scripts/cleanup.sh >> /var/log/cleanup.log 2>&1" > /etc/cron.d/shorts-cleanup
chmod 0644 /etc/cron.d/shorts-cleanup
cron

echo "Shorts: Starting web UI on port ${PORT:-8000}..."
exec uvicorn shorts.server:app --host 0.0.0.0 --port "${PORT:-8000}"
