FROM python:3.11-slim AS builder

# System deps needed to compile webrtcvad C extension
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files for layer caching
COPY pyproject.toml uv.lock ./

# Install deps (frozen lockfile, no dev)
RUN uv sync --frozen --no-dev

# ---------- runtime ----------
FROM python:3.11-slim

WORKDIR /app

# Copy virtualenv + app from builder
COPY --from=builder /app/.venv /app/.venv
COPY . .

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/')" || exit 1

CMD ["python", "main.py"]
