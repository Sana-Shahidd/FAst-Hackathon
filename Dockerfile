# Frontend pages + backend API + PDF renderer in one image.
# Base tag must match the pinned playwright version in requirements.txt.
# Runs as UID 1000 (the user Hugging Face Spaces uses; also fine on Railway/Render).
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-core fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
ARG GIT_SHA=dev
# Non-secret defaults (the host's Variables/Secrets override them). Model ids were verified with
# `python -m app.agents.smoke` (docs/DECISIONS.md, T-02).
ENV GIT_SHA=${GIT_SHA} PYTHONUNBUFFERED=1 \
    APP_ENV=production SESSION_COOKIE_SECURE=true \
    PROFILER_MODEL=gemini:gemini-3.1-flash-lite LEARNER_MODEL=gemini:gemini-3.1-flash-lite \
    CURATOR_MODEL=gemini:gemini-2.5-flash EDITOR_MODEL=gemini:gemini-2.5-flash \
    FALLBACK_MODEL=groq:qwen/qwen3.8-27b
RUN chown -R 1000:1000 /srv
USER 1000
ENV HOME=/home/ubuntu
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips='*'"]
