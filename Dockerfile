FROM python:3.11-slim

# System dependencies: ffmpeg + cron
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg cron && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies installed first for layer caching
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir yt-dlp && \
    pip install --no-cache-dir .

# Application code
COPY src/ src/
COPY scripts/ scripts/
RUN chmod +x scripts/*.sh

# Ensure working directory exists inside container
RUN mkdir -p /app/raw /app/output /app/transcripts /app/clips /app/working

EXPOSE 8000

ENTRYPOINT ["/app/scripts/start.sh"]
