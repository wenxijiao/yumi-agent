# Kumi HTTP server (core API). Mount a volume for ~/.kumi to persist config and memory.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    KUMI_LOG_LEVEL=INFO

COPY pyproject.toml MANIFEST.in README.md LICENSE NOTICE ./
COPY kumi ./kumi

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "-m", "kumi.core.api"]
