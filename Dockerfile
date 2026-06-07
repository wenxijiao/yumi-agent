# Yumi HTTP server (core API). Mount a volume for ~/.yumi to persist config and memory.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    YUMI_LOG_LEVEL=INFO

COPY pyproject.toml MANIFEST.in README.md LICENSE NOTICE ./
COPY yumi ./yumi

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "-m", "yumi.core.api"]
