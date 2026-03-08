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

# ---------- frontend build ----------
FROM node:20-slim AS frontend

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ---------- discord bot build ----------
FROM node:20-slim AS discord

WORKDIR /app/discord-bot
COPY discord-bot/package.json discord-bot/package-lock.json ./
RUN npm ci --omit=dev
COPY discord-bot/index.js .

# ---------- runtime ----------
FROM python:3.11-slim

# Install Node.js for discord bot sidecar
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtualenv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy app source
COPY . .

# Copy built frontend
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Copy discord bot with node_modules
COPY --from=discord /app/discord-bot /app/discord-bot

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/')" || exit 1

CMD ["sh", "-c", "node /app/discord-bot/index.js & python main.py"]
