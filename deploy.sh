#!/usr/bin/env bash
set -euo pipefail

# ─── Silas — One-Shot VPS Deploy ────────────────────────────────────
# Usage:
#   curl -sSL https://raw.githubusercontent.com/<you>/silas/main/deploy.sh | bash
#   — or —
#   chmod +x deploy.sh && ./deploy.sh
#
# Prerequisites: Ubuntu/Debian VPS with root or sudo access.
# This script installs Docker (if missing), clones the repo, and starts the game.
# ────────────────────────────────────────────────────────────────────

REPO_URL="${SILAS_REPO:-https://github.com/<you>/silas.git}"
BRANCH="${SILAS_BRANCH:-main}"
INSTALL_DIR="${SILAS_DIR:-/opt/silas}"
PORT="${PORT:-8080}"

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║   SILAS — One-Shot VPS Deploy    ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# ── 1. Install Docker if missing ────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "→ Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
    echo "  Docker installed."
else
    echo "→ Docker already installed."
fi

# ── 2. Install Docker Compose plugin if missing ─────────────────────
if ! docker compose version &>/dev/null; then
    echo "→ Installing Docker Compose plugin..."
    apt-get update -qq && apt-get install -y -qq docker-compose-plugin
    echo "  Docker Compose installed."
else
    echo "→ Docker Compose already available."
fi

# ── 3. Clone or pull the repo ───────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "→ Updating existing repo at $INSTALL_DIR..."
    git -C "$INSTALL_DIR" fetch origin "$BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
else
    echo "→ Cloning repo to $INSTALL_DIR..."
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── 4. Create .env if missing ───────────────────────────────────────
if [ ! -f .env ]; then
    echo ""
    read -rp "  Enter your GEMINI_API_KEY: " API_KEY
    echo "GEMINI_API_KEY=$API_KEY" > .env
    echo "  .env created."
else
    echo "→ .env already exists, keeping it."
fi

# ── 5. Build and start ──────────────────────────────────────────────
echo "→ Building and starting container..."
docker compose down --remove-orphans 2>/dev/null || true
docker compose up -d --build

echo ""
echo "  ✓ Silas is running!"
echo ""
echo "  Local:    http://localhost:$PORT"
echo "  Public:   http://$(curl -s ifconfig.me):$PORT"
echo ""
echo "  Logs:     docker compose -f $INSTALL_DIR/docker-compose.yml logs -f"
echo "  Stop:     docker compose -f $INSTALL_DIR/docker-compose.yml down"
echo "  Restart:  docker compose -f $INSTALL_DIR/docker-compose.yml restart"
echo ""
