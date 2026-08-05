# Hongbi / MyHongBi — full API + ffmpeg + whisper-capable image
# Suitable for: Railway / Render / Fly.io / self-hosted VPS
# NOT suitable for Vercel serverless as-is.

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PORT=8001

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY web_app.py ./
COPY src ./src
COPY templates ./templates
COPY static ./static
COPY data ./data
COPY .env.example ./.env.example

RUN mkdir -p generated_notes logs .cache

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# Whisper models download on first use into ~/.cache/whisper (persist via volume)
CMD ["sh", "-c", "uvicorn web_app:app --host 0.0.0.0 --port ${PORT}"]
