FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg cron curl unzip && \
    rm -rf /var/lib/apt/lists/*

# Install deno (required by yt-dlp for YouTube JS runtime)
RUN curl -fsSL https://deno.land/install.sh | sh && \
    echo 'export DENO_INSTALL="/root/.deno"' >> /etc/profile.d/deno.sh && \
    echo 'export PATH="$DENO_INSTALL/bin:$PATH"' >> /etc/profile.d/deno.sh
ENV DENO_INSTALL="/root/.deno"
ENV PATH="$DENO_INSTALL/bin:$PATH"

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir yt-dlp bgutil-ytdlp-pot-provider && \
    pip install --no-cache-dir .

COPY scripts/ scripts/
RUN chmod +x scripts/*.sh

RUN mkdir -p /app/raw /app/output /app/transcripts /app/clips /app/working

ENTRYPOINT ["/app/scripts/start.sh"]
