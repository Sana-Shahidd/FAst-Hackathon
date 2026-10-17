# Frontend pages + backend API + PDF renderer in one image.
# Base tag must match the pinned playwright version in requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-core fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA} PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
