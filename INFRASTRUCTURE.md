# Silas — Infrastructure Overview

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          PLAYER'S PHONE                                │
│                                                                        │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────────────────┐  │
│  │   Camera      │   │  Microphone   │   │     Browser (app.js)       │  │
│  │  768×768 JPEG │   │ 16kHz PCM     │   │                            │  │
│  │  1 FPS        │   │ AudioWorklet  │   │  ┌────────────────────┐   │  │
│  └──────┬───────┘   └──────┬───────┘   │  │   Web Audio API    │   │  │
│         │                  │            │  │                    │   │  │
│         │  tag=0x01        │  tag=0x02  │  │  Narration gain=1.0│   │  │
│         └──────────┬───────┘            │  │  Music    gain=0.25│   │  │
│                    │                    │  └────────────────────┘   │  │
│                    ▼                    │                            │  │
│           ┌────────────────┐            │  ┌────────────────────┐   │  │
│           │   WebSocket    │◄───────────┼──│  HUD Renderer      │   │  │
│           │   Client       │            │  │  Timer / Streak /  │   │  │
│           │                │───────────►│  │  Rank / Vibes /    │   │  │
│           └────────┬───────┘   JSON +   │  │  Tasks / Toasts /  │   │  │
│                    │          Binary     │  │  Narration         │   │  │
│                    │                    └────────────────────────────┘  │
└────────────────────┼───────────────────────────────────────────────────┘
                     │
                     │  WebSocket (ws:// or wss://)
                     │
┌────────────────────┼───────────────────────────────────────────────────┐
│                    ▼            GAME SERVER (Python)                    │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                        aiohttp Server                             │  │
│  │                       0.0.0.0:8080                                │  │
│  │                                                                   │  │
│  │   Routes:                                                         │  │
│  │     GET  /          → index.html     (JOYBAIT)                    │  │
│  │     WS   /ws/game   → Game WebSocket handler                     │  │
│  │     GET  /static/*  → Static files   (JS, CSS)                   │  │
│  └──────────────────────────────┬────────────────────────────────────┘  │
│                                 │                                       │
│                                 ▼                                       │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                        Orchestrator                               │  │
│  │                                                                   │  │
│  │   Wires all services via async callbacks.                         │  │
│  │   Routes: Gemini → GameState → Display                            │  │
│  │           Gemini → Brain (observations) → GameState (scoring)     │  │
│  │           Gemini → LyriaService (mood changes)                    │  │
│  │           Gemini → Display (VAD state)                            │  │
│  │           Brain  → GameState (parallel scoring pipeline)          │  │
│  │           Brain  → Gemini (contextual nudges + reconnect context) │  │
│  │           GameState timer → auto-trigger final_minute/victory     │  │
│  │                                                                   │  │
│  │   Also accepts CLI commands:                                      │  │
│  │     start | stop | score | penalize | music | say | status        │  │
│  └──┬─────────┬──────────┬──────────┬──────────┬────────────────────┘  │
│     │         │          │          │          │                        │
│     ▼         ▼          ▼          ▼          ▼                        │
│  ┌────────┐┌─────────┐┌────────┐┌────────┐┌──────────────┐            │
│  │Gemini  ││GameBrain││GameSt. ││Lyria   ││WebDisplay    │            │
│  │Service ││Service  ││Manager ││Service ││Service       │            │
│  │        ││         ││        ││        ││              │            │
│  │Live API││Flash    ││Vibes   ││Lyria   ││WebSocket     │            │
│  │VAD/FSM ││text API ││Streak  ││RealTime││binary proto  │            │
│  │Nudger  ││Memory   ││Timer   ││music   ││JSON state    │            │
│  │Tag     ││Scoring  ││Rank    ││9 moods ││VAD state     │            │
│  │parsing ││Nudge gen││Tasks   ││        ││              │            │
│  │(fallbk)││Context  ││        ││        ││              │            │
│  └───┬────┘└────┬────┘└────────┘└───┬────┘└──────────────┘            │
│      │          │                   │                                  │
└──────┼──────────┼───────────────────┼──────────────────────────────────┘
       │          │                   │
       ▼          ▼                   ▼
┌────────────┐ ┌────────────┐ ┌──────────────────┐
│ Gemini 2.5 │ │ Gemini 2.5 │ │  Google Lyria    │
│ Flash      │ │ Flash      │ │  RealTime        │
│            │ │ (Text API) │ │                  │
│ Live API   │ │            │ │  Music API (WS)  │
│ (WS)      │ │ Long-ctx   │ │  v1alpha         │
│ Native    │ │ memory +   │ │                  │
│ Audio     │ │ scoring    │ │  lyria-realtime- │
│            │ │ decisions  │ │  exp             │
└────────────┘ └────────────┘ └──────────────────┘
```

---

## Component Breakdown

### 1. Web Server — `aiohttp`

| Property | Value |
|----------|-------|
| Host | `0.0.0.0` |
| Port | `8080` |
| Framework | aiohttp (async Python) |
| Protocol | HTTP + WebSocket |
| Max WS Message | 4 MB |

The server serves the game HTML page and handles the game WebSocket endpoint. All I/O is non-blocking via `asyncio`.

**Entry point:** `main.py` → calls `src.server.create_app()`

### 2. Orchestrator — `src/orchestrator.py`

Central coordinator that wires all services together using a callback pattern. No service directly references another — the orchestrator registers callbacks on each and routes data between them.

```
Gemini.on_audio       → Display.send_narration_audio
Gemini.on_narration   → Display.send_narration_text + Brain.record_observation
Gemini.on_score       → GameState.score + Brain.record_score  (fallback path)
Gemini.on_penalize    → GameState.penalize + Brain.record_penalty  (fallback path)
Gemini.on_music       → Lyria.set_mood + Brain.record_mood_change
Gemini.on_task        → GameState.set_task + Brain.record_task + Display.send_event
Gemini.on_vad_state   → Display.send_vad_state + Brain.record_player_speech
Brain.on_score        → GameState.score  (primary scoring pipeline)
Brain.on_penalize     → GameState.penalize  (primary scoring pipeline)
Brain.on_music        → Lyria.set_mood
Brain.on_task         → GameState.set_task + Display.send_event
Brain → Gemini        (contextual nudge prompts + reconnect context restoration)
GameState.on_change   → Display.send_state
GameState.on_change   → Lyria.set_mood (auto: final_minute at ≤60s, victory/defeat at end)
GameState.on_event    → Display.send_event
Lyria.on_audio        → Display.send_music_audio
```

### 3. Gemini Service — `src/services/gemini_service.py`

Manages the real-time connection to Google's Gemini 2.5 Flash Live API.

| Property | Value |
|----------|-------|
| Model | `gemini-2.5-flash-native-audio-preview-12-2025` |
| Voice | `Aoede` (configurable via `GEMINI_VOICE` env var) |
| Input | Video frames (JPEG) + Mic audio (16kHz PCM) |
| Output | Narration audio (24kHz mono PCM) + Text with scoring tags |
| Compression | Sliding window context compression |
| Reconnect | Up to 5 consecutive errors before full reconnect |

**Camera Perspective — Rear (Outward-Facing):**

The player holds their phone with the **rear camera facing outward**. Gemini sees what is in front of the player — surroundings, other people, the environment. **The player is never visible.** Player actions are inferred by combining:

- **Audio** — player's voice (greetings, conversation, laughter) via mic
- **Scene** — who is visible in frame, proximity, reactions of other people
- **Context** — camera moving toward people = approaching; conversation audio + people in frame = engaging; static empty scene + silence = idle

This means some actions (e.g. gestures, facial expressions, body language) cannot be directly observed. Scoring and tasks are biased toward **audio-verifiable** actions (speak, ask, laugh, compliment) rather than visual-only actions (wave, smile, nod).

**Personality:**

Silas is the player's friend and wingman. Chill, warm, quick — talks like a real friend. One sentence replies, two max. Never sounds like a narrator, announcer, or NPC.

**Dual Mode — Conversation + Background Scoring:**

Silas operates in two modes that switch automatically:

- **MODE 1 — Background (default):** When no one is speaking, Silas checks the scene (outward camera + mic audio) via adaptive nudge prompts (8-20s intervals based on activity), scoring social interactions and penalizing inactivity. Can also drop tasks for the player.
- **MODE 2 — Conversation:** When the player speaks directly (detected via VAD), Silas responds naturally, 1-2 sentences. Scoring tags are optional during conversation. After responding, Silas waits for the next nudge.

**Nudger-Pause Behavior:**

The nudger automatically pauses when the player starts speaking (VAD enters LISTENING state) and resumes after a configurable delay (`NUDGE_RESUME_DELAY = 5` seconds) once the player stops. This prevents narration from overlapping with conversation. The nudger also skips nudging while Gemini is speaking as a defensive guard.

**VAD (Voice Activity Detection) — 3-State Finite State Machine:**

```
                  speech detected
    ┌──────┐ ──────────────────────► ┌─────────┐
    │ IDLE │                         │ PENDING │
    └──────┘ ◄────────────────────── └────┬────┘
                 onset timeout              │
                 (no sustained              │ sustained speech
                  speech in 0.3s)           │ for ≥ 0.3s
                                            ▼
                                     ┌───────────┐
                        silence      │ LISTENING │
    ┌──────┐ ◄── (1.5s timeout) ──── │           │
    │ IDLE │                         │ sends all │
    └──────┘                         │ buffered  │
                                     │ + live    │
                                     │ audio     │
                                     └───────────┘
```

- **IDLE:** Sends silence to Gemini. Waits for speech onset.
- **PENDING:** Buffers audio. If speech sustains ≥0.3s, transitions to LISTENING and flushes buffer. Otherwise discards and returns to IDLE.
- **LISTENING:** Streams audio directly to Gemini. Returns to IDLE after 1.5s of silence. Pauses the nudger.
- While Gemini is speaking, mic is muted (prevents echo/feedback).

VAD state changes are sent to the frontend via `{"type": "vad_state", "state": "LISTENING"|"IDLE"|"PENDING"}` messages, enabling the mic-dot listening indicator.

**Tag Parsing:**

Gemini's text output is parsed for embedded control tags:

```
<<SCORE action_type points description>>    → triggers GameState.score()
<<PENALIZE action_type points>>             → triggers GameState.penalize()
<<MUSIC mood_name>>                         → triggers LyriaService.set_mood()
<<TASK task_description bonus_points>>      → triggers GameState.set_task()
```

Tags are stripped from narration text before display. Tag parsing from the Live API serves as a **fallback scoring path** — the primary scoring pipeline is handled by the Game Brain service (see below).

**Adaptive Nudger:**

A background task that sends prompts to Gemini after an initial 12s delay. Uses **adaptive intervals** based on game state:

| Condition | Interval |
|-----------|----------|
| Player idle (>15s since last score) | 8s |
| Player actively socializing | 20s |
| Final minute (timer ≤ 60s) | 12s |

Nudge prompts are generated contextually by the Game Brain when available, falling back to static prompt rotation. Includes brain context summary + game state. Automatically pauses during player speech and resumes after a 5-second delay.

**Context-Preserving Reconnect:**

When the Gemini Live API session drops and reconnects, the Game Brain provides a full context restoration summary that is injected into the new session. This ensures Silas maintains continuity — remembering who the player talked to, what happened, and the current game arc.

### 4. Game Brain Service — `src/services/game_brain.py`

Long-context memory and scoring model using Gemini 2.5 Flash (text API, non-streaming).

| Property | Value |
|----------|-------|
| Model | `gemini-2.5-flash` |
| API | `generateContent` (text, not Live API) |
| Update Interval | 10 seconds |
| Max History | 100 events (rolling) |
| Temperature | 0.3 (scoring) / 0.5 (nudge generation) |

**Responsibilities:**

- **Game Memory:** Maintains a rolling history of all game events (observations, scores, penalties, mood changes, tasks, player speech) with timestamps
- **Parallel Scoring Pipeline:** Periodically analyzes pending observations and returns structured JSON scoring decisions (scores, penalties, mood changes, tasks) — eliminating regex fragility
- **Contextual Nudge Generation:** Generates smart, situation-aware nudge prompts for the Live API narrator based on full game history and player patterns
- **Context Restoration:** Provides full session summaries for seamless reconnection after Live API disconnects

**Scoring Response Format:**
```json
{
  "scores": [{"action": "greeting", "points": 15, "description": "approached new person"}],
  "penalties": [],
  "mood": "approaching",
  "task": {"text": "give someone a high five", "bonus": 20},
  "observations_summary": "Player engaged with person near window..."
}
```

**Dual Scoring Pipeline:**
Both the Live API (tag parsing, fallback) and Game Brain (structured JSON, primary) can score events. The orchestrator routes both paths to GameState. The Game Brain is more reliable (structured JSON output) while the Live API path provides lower-latency scoring for obvious actions.

### 5. Lyria Service — `src/services/lyria_service.py`

Manages real-time adaptive music generation via Google's Lyria RealTime API.

| Property | Value |
|----------|-------|
| Model | `models/lyria-realtime-exp` |
| API Version | `v1alpha` |
| Output | 48kHz stereo PCM audio |
| Default BPM | 100 |
| Guidance | 4.0 |
| Temperature | 1.1 |

**9 Music Moods:**

| Mood | Density | Brightness | Prompt |
|------|---------|------------|--------|
| `idle` | 0.2 | 0.3 | ambient lo-fi chill melancholy sparse piano |
| `approaching` | 0.4 | 0.5 | hopeful building anticipation light acoustic guitar |
| `action_scored` | 0.7 | 0.8 | triumphant bright celebration orchestral uplifting |
| `streak` | 0.8 | 0.9 | energetic driving momentum upbeat electronic funk |
| `legendary` | 1.0 | 1.0 | epic heroic powerful full orchestra electronic hybrid |
| `draining` | 0.15 | 0.2 | somber lonely sparse desolate ambient dark |
| `final_minute` | 0.9 | 0.7 | urgent tense racing against time dramatic percussion |
| `victory` | 0.9 | 1.0 | victorious celebration triumphant fanfare bright joyful |
| `defeat` | 0.3 | 0.3 | bittersweet reflective gentle piano fading |

Mood transitions update density, brightness, and weighted prompt. Duplicate mood changes are ignored.

### 6. Game State Manager — `src/services/game_state.py`

Manages all game logic — scoring, streaks, timer, rank calculation, and task tracking.

| Property | Value |
|----------|-------|
| Game Duration | 180 seconds (3 minutes) |
| Timer Tick | 1 second |
| Vibes Floor | 0 (never goes negative) |

**Streak Multiplier:**

| Streak | Multiplier |
|--------|------------|
| 0–2 | 1x |
| 3–4 | 2x |
| 5+ | 3x |

Any penalty resets the streak to 0.

**Rank Thresholds:**

| Rank | Vibes Required |
|------|----------------|
| Goated | ≥ 700 |
| Fire | ≥ 400 |
| Valid | ≥ 200 |
| Basic | ≥ 0 |

**Task System:**

Silas can assign mini-challenges via `<<TASK>>` tags. The active task is displayed in a task bar in the HUD. When the task is completed (scored via a matching social action), bonus vibes are awarded and the tasks-completed counter increments.

**Auto-triggers:**
- Timer ≤ 60s → music mood changes to `final_minute`
- Game over + vibes ≥ 400 → music mood `victory`
- Game over + vibes < 400 → music mood `defeat`

### 7. Display Service — `src/display/web_display.py`

Abstracts the WebSocket output channel. Implements `DisplayService` (abstract base in `src/display/base.py`).

**Outbound WebSocket Protocol:**

| Type | Format | Content |
|------|--------|---------|
| State update | JSON | `{"type": "state", "data": {...}}` |
| Score/Penalty/Task event | JSON | `{"type": "event", "data": {...}}` |
| Narration text | JSON | `{"type": "narration", "text": "..."}` |
| VAD state | JSON | `{"type": "vad_state", "state": "LISTENING\|IDLE\|PENDING"}` |
| Narration audio | Binary | `0x01` + 24kHz mono PCM bytes |
| Music audio | Binary | `0x02` + 48kHz stereo PCM bytes |

**Inbound WebSocket Protocol (from client):**

| Type | Format | Content |
|------|--------|---------|
| Camera frame | Binary | `0x01` + JPEG bytes |
| Mic audio | Binary | `0x02` + 16kHz PCM bytes |
| Intro request | JSON | `{"type": "intro"}` |
| Start game | JSON | `{"type": "start"}` |
| Stop game | JSON | `{"type": "stop"}` |

### 8. Frontend Client — `static/app.js`

Single-page game client running in the phone browser.

**Two-Phase Startup:**

```
 ┌────────────────┐      click       ┌────────────────┐
 │  LET'S GO      │ ──────────────►  │  Loading...    │
 │  (idle)        │                  │  Init camera,  │
 └────────────────┘                  │  mic, WS,      │
                                     │  request intro │
                                     └───────┬────────┘
                                             │
                                      intro audio ends
                                      (2s silence gap)
                                             │
                                             ▼
                                     ┌────────────────┐
                                     │  START VIBING  │
                                     │  (intro done)  │
                                     └───────┬────────┘
                                             │
                                          click
                                             │
                                             ▼
                                     ┌────────────────┐
                                     │  GAME ACTIVE   │
                                     │  HUD visible   │
                                     │  Timer running │
                                     └───────┬────────┘
                                             │
                                        timer = 0
                                             │
                                             ▼
                                     ┌────────────────┐
                                     │  GAME OVER     │
                                     │  Final stats   │
                                     │  RUN IT BACK   │
                                     └────────────────┘
```

**Audio Pipeline:**

```
Server narration (24kHz mono PCM)
  → Int16 → Float32 → AudioBuffer → BufferSource → GainNode(1.0) → Destination

Server music (48kHz stereo PCM)
  → Int16 → Float32 (L/R split) → AudioBuffer → BufferSource → GainNode(0.25) → Destination
```

Both streams use scheduled playback (`narrationNextTime` / `musicNextTime`) to prevent gaps or overlaps.

**Mic Listening Indicator:**

The frontend receives `vad_state` JSON messages from the server. When the state is `LISTENING`, the mic dot indicator lights up to show the player that Silas is hearing them. This is driven entirely by server-side VAD state rather than client-side audio detection.

---

## Data Flow

### Unified Game Mode — Conversation + Background Scoring

```
1. Phone captures camera frame (768×768 JPEG, 1 FPS)
2. Phone captures mic audio (16kHz PCM via AudioWorklet)
3. Both sent over WebSocket with binary tags (0x01 camera, 0x02 mic)
4. Server routes frames + audio to GeminiService
5. GeminiService sends to Gemini Live API (WebSocket)
6. VAD detects player speech:
   - If player is speaking → nudger pauses, Silas responds as homie (MODE 2)
   - If player is silent → nudger sends periodic prompts, Silas scores silently (MODE 1)
7. Gemini processes video + audio, returns:
   - Response audio (24kHz mono PCM) → streamed to client
   - Text with embedded tags → parsed by GeminiService
8. Tags extracted:
   - <<SCORE>> → GameStateManager.score() → vibes/streak updated
   - <<PENALIZE>> → GameStateManager.penalize() → streak reset
   - <<MUSIC>> → LyriaService.set_mood() → music changes
   - <<TASK>> → GameStateManager.set_task() → task bar shown
9. GameState changes → state JSON sent to client → HUD updates
10. Score/penalty/task events → event JSON sent to client → toast shown
11. VAD state changes → vad_state JSON sent to client → mic dot indicator
12. Lyria generates music audio (48kHz stereo) → streamed to client
13. Client mixes narration + music via Web Audio API → speaker output
```

---

## File Structure

```
silas/
├── main.py                         # Entry point: aiohttp server + CLI
├── pyproject.toml                  # Dependencies + project metadata
├── .env                            # GEMINI_API_KEY
├── .python-version                 # 3.11
│
├── src/
│   ├── __init__.py
│   ├── config.py                   # All constants (ports, models, rates, thresholds)
│   ├── server.py                   # Route definitions + WS handler
│   ├── orchestrator.py             # Service wiring + callback routing
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── gemini_service.py       # Gemini Live API + VAD + tag parsing + adaptive nudger
│   │   ├── game_brain.py           # Game Brain: long-context memory + parallel scoring
│   │   ├── lyria_service.py        # Lyria RealTime music generation
│   │   └── game_state.py           # Vibes, streak, timer, rank, task logic
│   │
│   └── display/
│       ├── __init__.py
│       ├── base.py                 # DisplayService abstract interface
│       └── web_display.py          # WebSocket display implementation
│
├── static/
│   ├── app.js                      # Game client (camera, mic, WS, HUD, audio, VAD indicator, tasks)
│   ├── mic-processor.js            # AudioWorklet: resamples mic to 16kHz PCM
│   └── style.css                   # Game UI styles (coral/orange theme)
│
├── templates/
│   ├── index.html                  # Game page (JOYBAIT)
│   └── camera.html                 # Camera test page
│
├── tests/
│   ├── test_gemini_live.py         # Full game mode integration test
│   ├── test_gemini_chat.py         # Chat mode integration test
│   ├── test_lyria_music.py         # Music generation + mood cycling test
│   └── test_phone_camera.py        # Camera enumeration + streaming test
│
└── docs/
    └── hackathon-plan.md           # Original design document
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Runtime | Python 3.11 | Async server |
| Package Manager | uv | Fast dependency management |
| Web Framework | aiohttp | HTTP server + WebSocket |
| AI Narration | Gemini 2.5 Flash (Live API) | Real-time multimodal AI |
| AI Memory | Gemini 2.5 Flash (Text API) | Long-context game brain + scoring |
| AI Music | Lyria RealTime (v1alpha) | Adaptive music generation |
| Voice Detection | webrtcvad | 3-state VAD FSM |
| Frontend | Vanilla JS + HTML5 + CSS3 | No framework dependency |
| Audio | Web Audio API + AudioWorklet | Real-time audio mixing |
| Camera | MediaDevices API | Phone camera capture |
| Env Config | python-dotenv | API key management |

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | — | Google AI API key for Gemini + Lyria |
| `GEMINI_VOICE` | No | `Aoede` | Gemini TTS voice name |

---

## Network Topology

```
┌──────────────┐         ┌──────────────┐         ┌──────────────────┐
│              │  HTTP/   │              │  WS     │                  │
│  Phone       │  WS     │  Silas       │ ◄─────► │  Gemini Live API │
│  Browser     │ ◄─────► │  Server      │         │  (Google)        │
│              │         │  :8080       │         └──────────────────┘
│              │         │              │
│              │         │              │  WS     ┌──────────────────┐
│              │         │              │ ◄─────► │  Lyria RealTime  │
│              │         │              │         │  (Google)        │
└──────────────┘         └──────────────┘         └──────────────────┘

Local network or                         Outbound WebSocket
Cloudflare tunnel                        connections to Google
```

**Deployment options:**
- Local: `python main.py` → access via LAN IP
- Tunnel: `cloudflared tunnel --url http://localhost:8080` → HTTPS URL for phone access

---

## Audio Sample Rates

| Stream | Rate | Channels | Format | Direction |
|--------|------|----------|--------|-----------|
| Mic input | 16,000 Hz | Mono | PCM int16 | Phone → Server → Gemini |
| Narration output | 24,000 Hz | Mono | PCM int16 | Gemini → Server → Phone |
| Music output | 48,000 Hz | Stereo | PCM int16 | Lyria → Server → Phone |

---

## Concurrency Model

All services run in a single Python process using `asyncio`:

```
main event loop
├── aiohttp server (handles HTTP + WS connections)
├── GeminiService._receive_loop     (reads Gemini responses)
├── GeminiService._nudger           (adaptive scoring prompts, brain-powered)
├── GameBrainService._sync_loop     (periodic observation analysis + scoring)
├── LyriaService._receive_loop      (reads music audio chunks)
├── GameStateManager._run_timer     (1s tick countdown)
└── stdin_reader                    (CLI commands, optional)
```

All callbacks between services use `asyncio.create_task()` for non-blocking dispatch. No threads, no multiprocessing — pure async I/O.
