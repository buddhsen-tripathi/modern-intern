FROM python:3.11-slim

# Install system deps for pyaudio and webrtcvad
RUN apt-get update && apt-get install -y --no-install-recommends \
    portaudio19-dev \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev deps, frozen lockfile)
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Expose the game server port
EXPOSE 8080

# Run with the virtual environment python
CMD ["uv", "run", "python", "main.py"]
