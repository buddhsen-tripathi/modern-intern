# Modern Intern

CONTRIBUTORS
- Buddhsen Tripathi
- Esparance Tuyishime
- Olivia Iarmak

Demo Link: https://clownfish-app-7ftwi.ondigitalocean.app/

A voice-only AI personal assistant powered by Google Gemini 2.5 Flash Live API. Speak commands, get things done — notes, emails, meetings, and more — all through natural voice interaction.

## Features

- **Voice Commands** — speak naturally to take notes, draft/send/read emails, create calendar events, and record meetings
- **Real-Time Voice Activity Detection** — WebRTC VAD detects when you're speaking and routes audio to Gemini
- **Live Narration** — Gemini responds with spoken audio in real time
- **Terminal-Style HUD** — web interface with live activity logs, status indicators, and narration display
- **Discord Integration** — action results posted to a Discord channel via a Node.js sidecar bot
- **Fully Async** — built on `aiohttp` with non-blocking I/O throughout

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.11+, aiohttp, asyncio |
| AI | Google Gemini 2.5 Flash (Live API + Text API) |
| Voice | WebRTC VAD, Web Audio API, AudioWorklet |
| Frontend | React 19, Vite |
| Discord Bot | Node.js, Chat SDK |
| Deployment | Docker, Docker Compose |

## Project Structure

```
modern-intern/
├── main.py                    # Entry point: aiohttp server + CLI
├── src/
│   ├── config.py              # Constants and audio parameters
│   ├── server.py              # WebSocket handler and routes
│   ├── orchestrator.py        # Routes voice commands to agents
│   ├── agents/                # Task-specific agents
│   │   ├── note_agent.py      # Note taking
│   │   ├── email_agent.py     # Gmail draft/send/read
│   │   ├── calendar_agent.py  # Calendar events (stub)
│   │   └── meeting_agent.py   # Meeting minutes + summarization
│   ├── services/
│   │   ├── gemini_service.py  # Gemini Live API client + VAD
│   │   ├── discord_service.py # Discord notification sender
│   │   └── telegram_service.py
│   └── display/
│       └── web_display.py     # WebSocket state/audio/text output
├── frontend/                  # React + Vite UI
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── StartScreen.jsx
│   │   │   └── HUD.jsx
│   │   └── hooks/
│   │       └── useModernIntern.js
│   └── dist/
├── discord-bot/               # Node.js Discord sidecar
├── static/                    # Legacy fallback UI
├── templates/                 # Legacy HTML template
├── tests/                     # Gemini, camera, audio tests
├── docs/                      # Hackathon plans and concepts
├── Dockerfile
├── docker-compose.yml
└── deploy.sh                  # One-shot VPS deployment
```

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- A [Google Gemini API key](https://aistudio.google.com/apikey)

### Setup

```bash
# Install dependencies
uv sync

# Create .env file
cat > .env << EOF
GEMINI_API_KEY=your_key_here
GEMINI_VOICE=Aoede
PORT=8080
EOF

# Run
python main.py
```

Open http://localhost:8080, grant microphone access, and click **START**.

### With Docker

```bash
docker compose up --build
```

## Voice Commands

| Command | What it does |
|---------|-------------|
| `"take note"` / `"note end"` | Dictate and save a note |
| `"draft email to [person] about [subject]"` | Compose an email |
| `"send email"` | Send the drafted email |
| `"read email"` | Read recent emails aloud |
| `"calendar event [description]"` | Create a calendar event |
| `"start meeting"` / `"stop meeting"` | Record and summarize a meeting |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `GEMINI_VOICE` | No | `Aoede` | Gemini TTS voice |
| `PORT` | No | `8080` | Server port |
| `GMAIL_ADDRESS` | No | — | Gmail account for email agent |
| `GMAIL_APP_PASSWORD` | No | — | Gmail app-specific password |
| `DISCORD_CHANNEL_ID` | No | — | Discord channel (`discord:guildid:channelid`) |
| `DISCORD_NOTIFY_PORT` | No | `3100` | Discord bot sidecar port |

## CLI Commands

When running in a terminal, you can also use these commands:

- `start` — begin listening session
- `stop` — end session
- `say <text>` — inject text as if spoken
- `status` — print current state as JSON
- `help` — show available commands

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for full deployment instructions including:

- DigitalOcean App Platform (managed)
- VPS with Docker (one-command deploy)
- HTTPS setup with Caddy

## Architecture

See [INFRASTRUCTURE.md](INFRASTRUCTURE.md) for system architecture diagrams and detailed component documentation.

## License

MIT