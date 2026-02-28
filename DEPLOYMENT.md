# Silas — Deployment Guide

Two deployment paths: **DigitalOcean App Platform** (managed, auto-deploy from GitHub) or **any VPS with Docker** (one command).

---

## Option 1: DigitalOcean App Platform

Auto-deploys from GitHub on every push. Handles SSL, domains, and scaling.

### Via DigitalOcean UI

1. Go to [cloud.digitalocean.com/apps](https://cloud.digitalocean.com/apps)
2. **Create App** → select your GitHub repo → branch `main`
3. DO auto-detects the `Dockerfile` — accept defaults
4. In **Environment Variables**, add:
   - `GEMINI_API_KEY` = your key (mark as **Encrypt**)
5. Pick plan: **Basic $5/mo** (1 vCPU, 512 MB) is enough
6. Deploy

The `.do/app.yaml` in this repo is pre-configured and will be picked up automatically if you use the DO CLI instead.

### Via `doctl` CLI

```bash
# Install doctl: https://docs.digitalocean.com/reference/doctl/how-to/install/
doctl auth init

# Create the app from spec (set your API key first)
doctl apps create --spec .do/app.yaml

# After creation, set the secret via UI or:
doctl apps update <app-id> --spec .do/app.yaml
```

### Custom Domain

```bash
# In the DO dashboard: Settings → Domains → Add Domain
# Point your DNS A record to the provided IP, or use a CNAME to the .ondigitalocean.app URL.
```

---

## Option 2: One-Shot VPS Docker Deploy

Works on any Ubuntu/Debian VPS (DigitalOcean Droplet, Hetzner, Linode, AWS EC2, etc.). Single command installs Docker, clones the repo, builds, and starts the container.

### Quick Start

SSH into your VPS and run:

```bash
# Set your repo URL first (replace <you>)
export SILAS_REPO=https://github.com/<you>/silas.git

# One-shot deploy
curl -sSL https://raw.githubusercontent.com/<you>/silas/main/deploy.sh | bash
```

Or clone manually and run:

```bash
git clone https://github.com/<you>/silas.git /opt/silas
cd /opt/silas

# Create .env
echo "GEMINI_API_KEY=your_key_here" > .env

# Build and start
docker compose up -d --build
```

### What the Script Does

1. Installs Docker + Docker Compose (if missing)
2. Clones/updates the repo to `/opt/silas`
3. Prompts for `GEMINI_API_KEY` if `.env` doesn't exist
4. Builds the multi-stage Docker image
5. Starts the container on port 8080

### Management

```bash
# View logs
docker compose logs -f

# Restart
docker compose restart

# Stop
docker compose down

# Update to latest code
cd /opt/silas
git pull
docker compose up -d --build
```

### Firewall

Make sure port 8080 (or your chosen port) is open:

```bash
# UFW (Ubuntu)
ufw allow 8080/tcp

# DigitalOcean Droplet: also open port in the Cloud Firewall via dashboard
```

### HTTPS with Caddy (Optional)

For auto-SSL with a custom domain, add a Caddy reverse proxy:

```bash
apt install -y caddy

# /etc/caddy/Caddyfile
# yourdomain.com {
#     reverse_proxy localhost:8080
# }

systemctl restart caddy
```

Caddy auto-provisions Let's Encrypt certificates. WebSocket (`wss://`) works automatically.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | Google AI API key for Gemini + Lyria |
| `GEMINI_VOICE` | No | `Aoede` | Gemini TTS voice name |
| `PORT` | No | `8080` | Server listen port |

## Local Docker Test

```bash
docker compose up --build

# Open http://localhost:8080
```

## Architecture Notes

- **Single instance only** — in-memory state, no database. Don't scale horizontally.
- **~100-200 MB RAM** per game session (WS connections + audio buffers). 512 MB is plenty.
- **I/O-bound** — single shared vCPU is sufficient.
- **Long-lived WebSockets** — both DO App Platform and raw Docker support persistent WS connections with no timeout issues.
