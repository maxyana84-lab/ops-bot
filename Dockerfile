# syntax=docker/dockerfile:1

# --- Build stage: install dependencies into an isolated prefix -----------------
FROM python:3.13-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Runtime stage: minimal image, non-root user ------------------------------
FROM python:3.13-slim
LABEL org.opencontainers.image.title="ops-bot" \
      org.opencontainers.image.description="Telegram bot for infrastructure alerts and service status"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TARGETS_FILE=/app/config/targets.yaml

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
COPY config ./config

USER 10001
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"

CMD ["python", "-m", "app.main"]
