"""Gemini Live API service with VAD — personal assistant mode."""

import asyncio
import logging
import re
import time

import webrtcvad
from google import genai
from google.genai import types

from src.config import (
    GEMINI_MODEL,
    GEMINI_VOICE,
    MIC_SAMPLE_RATE,
    SPEECH_ONSET_SEC,
    SILENCE_TIMEOUT_SEC,
    VAD_AGGRESSIVENESS,
    VAD_CHUNK_SIZE,
    WATCHER_ACTIVE_INTERVAL,
    WATCHER_IDLE_INTERVAL,
    WATCHER_RESUME_DELAY,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are SILAS — a smart personal assistant that sees and hears through the user's phone.

PERSONALITY: Calm, efficient, helpful. Talk like a capable assistant — concise and clear.
ONE sentence replies, two max. No fluff.

─── WHAT YOU SEE AND HEAR ─────────────────────────────────
The user is holding their phone with the REAR camera facing outward.
You see what's IN FRONT of the user — their surroundings, people, whiteboards,
documents, screens, the environment. You CANNOT see the user themselves.

You also hear the user's microphone, which picks up their voice
and ambient audio (other people talking, meetings, background noise).

─── CONVERSATION (your main job) ──────────────────────────
When the user speaks to you, RESPOND. You're their assistant.
1. Reply concisely — ONE sentence preferred
2. If they ask you to do something, acknowledge and emit the appropriate ACTION tag
3. After responding, go QUIET — wait for them to speak again

─── GESTURE RECOGNITION ───────────────────────────────────
Watch the camera feed for these hand gestures:
• THUMBS UP — confirm / acknowledge current action
• OPEN PALM (stop hand) — take a note of what was just said or seen
• PEACE SIGN (two fingers) — email related action
• POINTING UP (index finger) — create a calendar event
• WAVE — start or stop taking meeting minutes
• OK SIGN (thumb+index circle) — send / confirm action

When you detect a gesture, emit a <<GESTURE>> tag.

─── ACTION TAGS ────────────────────────────────────────────
Emit these on their own line based on gestures OR voice commands:

<<GESTURE gesture_name>>
gesture_name: thumbs_up, open_palm, peace_sign, point_up, wave, ok_sign
Emit when you visually detect a gesture in the camera feed.

<<ACTION action_type json_params>>
action_type and when to emit:

  note — user asks to take a note, or open_palm gesture
    params: {"content": "the note text"}

  meeting_minutes — user says "take minutes" or wave gesture
    params: {"command": "start"} or {"command": "stop"}

  draft_email — user asks to draft an email, or peace_sign gesture
    params: {"to": "recipient", "subject": "subject line", "body": "email body"}
    Fill in what you can from conversation context. Use "" for unknown fields.

  send_email — user says "send it" or ok_sign gesture after drafting
    params: {}

  read_email — user asks to read/check email
    params: {"count": 5}

  calendar_event — user asks to schedule something, or point_up gesture
    params: {"title": "event title", "start": "ISO datetime", "duration_minutes": 30, "description": ""}
    Infer details from conversation. Use reasonable defaults.

RULES:
- NEVER announce tags aloud. Don't say "I'm creating an action tag."
- Tags are silent metadata — the user sees results on screen.
- When you detect a gesture, briefly acknowledge it naturally
  (e.g., "Got it, noting that down" for open_palm)
- Combine gesture + recent voice context to fill ACTION params intelligently
- When told "CHECK ONLY", observe the scene silently and only emit tags if relevant. No spoken words.
- If a gesture is ambiguous, ask the user what they'd like to do."""

GESTURE_RE = re.compile(r"<<GESTURE\s+(\w+)>>")
ACTION_RE = re.compile(r"<<ACTION\s+(\w+)\s+(\{.*?\})>>", re.DOTALL)

# Watcher prompts — periodic scene check-ins
WATCHER_PROMPTS = [
    "CHECK ONLY. Glance at the scene and listen. Any gestures? Any context worth noting? Emit tags only if relevant.",
    "CHECK ONLY. Quick look — any hand gestures visible? Any voice requests? Tags only, no talking.",
    "CHECK ONLY. Scene + audio check. Gestures? Requests? Tag if needed, otherwise stay quiet.",
]

MAX_RECONNECT_ATTEMPTS = 5
MAX_OBSERVATION_BUFFER = 10


class GeminiService:
    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)
        self._session = None
        self._ctx = None
        self._running = False

        # VAD
        self._vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self._mic_state = "IDLE"
        self._gemini_speaking = False
        self._speech_start = 0.0
        self._last_speech = 0.0
        self._pending_buffer = []
        self._silence = b"\x00" * VAD_CHUNK_SIZE * 2

        # Watcher-pause state
        self._watcher_paused = False
        self._player_stopped_speaking_at = 0.0
        self._user_interacted = False

        # Observation buffer for context
        self._observation_buffer: list[str] = []

        # Callbacks
        self._on_audio = None
        self._on_narration = None
        self._on_gesture = None
        self._on_action = None
        self._on_vad_state = None

        self._receive_task = None
        self._watcher_task = None

    def set_callbacks(self, on_audio=None, on_narration=None,
                      on_gesture=None, on_action=None, on_vad_state=None):
        self._on_audio = on_audio
        self._on_narration = on_narration
        self._on_gesture = on_gesture
        self._on_action = on_action
        self._on_vad_state = on_vad_state

    @property
    def connected(self) -> bool:
        return self._session is not None and self._running

    def _build_live_config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text=SYSTEM_PROMPT)]
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=GEMINI_VOICE,
                    )
                )
            ),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
        )

    async def connect(self):
        """Connect to Gemini and play intro."""
        log.info("Connecting to Gemini Live API...")
        self._observation_buffer.clear()
        config = self._build_live_config()
        self._ctx = self._client.aio.live.connect(
            model=GEMINI_MODEL, config=config,
        )
        self._session = await self._ctx.__aenter__()
        self._running = True
        log.info("Connected to Gemini (voice=%s)", GEMINI_VOICE)

        await self._session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=(
                    "Introduce yourself as Silas in one short sentence. "
                    "You're a personal assistant ready to help. "
                    "Calm and efficient. No action tags yet — just the intro."
                ))],
            ),
            turn_complete=True,
        )
        log.info("Sent intro prompt")
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def start_session(self):
        """Start watching for gestures and voice commands."""
        if not self.connected:
            await self.connect()
            await asyncio.sleep(1)

        await self._session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=(
                    "Session is active. Begin watching the video feed for hand gestures "
                    "and listening for voice commands. Emit <<GESTURE>> and <<ACTION>> "
                    "tags when appropriate. Go."
                ))],
            ),
            turn_complete=True,
        )
        log.info("Session started — watching for gestures and commands")
        self._watcher_task = asyncio.create_task(self._watcher())

    async def stop(self):
        self._running = False
        for task in (self._receive_task, self._watcher_task):
            if task:
                task.cancel()
        if self._ctx:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception:
                pass
            self._ctx = None
            self._session = None

    async def send_video_frame(self, jpeg_bytes: bytes):
        if not self._session or not self._running:
            return
        try:
            await self._session.send_realtime_input(
                video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg"),
            )
        except Exception as e:
            log.error(f"Error sending video: {e}")

    def _fire_vad_state(self, state: str):
        if self._on_vad_state:
            asyncio.create_task(self._on_vad_state(state))

    async def send_mic_audio(self, pcm_data: bytes):
        """Process mic audio through 3-state VAD FSM and forward to Gemini."""
        if not self._session or not self._running:
            return

        now = time.monotonic()

        try:
            is_speech = self._vad.is_speech(pcm_data, MIC_SAMPLE_RATE)
        except Exception:
            is_speech = False

        prev_state = self._mic_state

        if self._gemini_speaking:
            await self._send_silence()
            if self._mic_state != "IDLE":
                self._pending_buffer = []
                self._mic_state = "IDLE"
            if prev_state != self._mic_state:
                self._fire_vad_state(self._mic_state)
            return

        if self._mic_state == "IDLE":
            if is_speech:
                self._speech_start = now
                self._pending_buffer = [pcm_data]
                self._mic_state = "PENDING"
            else:
                await self._send_silence()

        elif self._mic_state == "PENDING":
            self._pending_buffer.append(pcm_data)
            if is_speech:
                if now - self._speech_start >= SPEECH_ONSET_SEC:
                    for chunk in self._pending_buffer:
                        await self._send_audio(chunk)
                    self._pending_buffer = []
                    self._last_speech = now
                    self._mic_state = "LISTENING"
                    self._watcher_paused = True
                    if not self._user_interacted:
                        self._user_interacted = True
            else:
                if now - self._speech_start > SPEECH_ONSET_SEC:
                    self._pending_buffer = []
                    self._mic_state = "IDLE"

        elif self._mic_state == "LISTENING":
            await self._send_audio(pcm_data)
            if is_speech:
                self._last_speech = now
            if now - self._last_speech > SILENCE_TIMEOUT_SEC:
                self._mic_state = "IDLE"
                self._player_stopped_speaking_at = now
                asyncio.create_task(self._signal_user_done())

        if self._mic_state != prev_state:
            self._fire_vad_state(self._mic_state)

    async def _signal_user_done(self):
        if not self._session or not self._running:
            return
        try:
            await self._session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text="reply")],
                ),
                turn_complete=True,
            )
        except Exception as e:
            log.error(f"Error sending user-done signal: {e}")

    async def inject_narration(self, text: str):
        log.info("NARRATION (injected): %s", text)
        self._parse_and_dispatch(text, trigger="injected")

    async def _send_silence(self):
        try:
            await self._session.send_realtime_input(
                audio=types.Blob(data=self._silence, mime_type="audio/pcm;rate=16000"),
            )
        except Exception:
            pass

    async def _send_audio(self, pcm_data: bytes):
        try:
            await self._session.send_realtime_input(
                audio=types.Blob(data=pcm_data, mime_type="audio/pcm;rate=16000"),
            )
        except Exception as e:
            log.error(f"Error sending audio: {e}")

    async def _receive_loop(self):
        text_buf = ""
        consecutive_errors = 0
        try:
            while self._running:
                try:
                    async for msg in self._session.receive():
                        if not self._running:
                            break

                        if msg.data:
                            if not self._gemini_speaking:
                                self._gemini_speaking = True
                            if self._on_audio:
                                asyncio.create_task(self._on_audio(msg.data))

                        if msg.text:
                            text_buf += msg.text

                        if hasattr(msg, "server_content") and msg.server_content:
                            sc = msg.server_content
                            if hasattr(sc, "turn_complete") and sc.turn_complete:
                                self._gemini_speaking = False
                                if text_buf.strip():
                                    log.debug("Gemini raw text: %s", text_buf)
                                    self._parse_and_dispatch(
                                        text_buf, trigger="gemini_response"
                                    )
                                text_buf = ""

                    consecutive_errors = 0

                except Exception as e:
                    if not self._running:
                        break
                    consecutive_errors += 1
                    log.error(
                        "Gemini receive error (%d/%d): %s",
                        consecutive_errors, MAX_RECONNECT_ATTEMPTS, e,
                    )
                    if consecutive_errors >= MAX_RECONNECT_ATTEMPTS:
                        log.warning("Attempting full reconnect...")
                        await self._reconnect()
                        consecutive_errors = 0
                    else:
                        await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    async def _reconnect(self):
        if self._ctx:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception:
                pass
        try:
            config = self._build_live_config()
            self._ctx = self._client.aio.live.connect(
                model=GEMINI_MODEL, config=config,
            )
            self._session = await self._ctx.__aenter__()
            log.info("Gemini reconnected successfully")
        except Exception as e:
            log.error("Gemini reconnect failed: %s", e)
            await asyncio.sleep(5.0)

    def _parse_and_dispatch(self, text: str, trigger: str = "unknown"):
        # Strip tags for display
        display = GESTURE_RE.sub("", text)
        display = ACTION_RE.sub("", display).strip()
        if display:
            log.info("NARRATION (trigger=%s): %s", trigger, display)
            self._observation_buffer.append(display)
            if len(self._observation_buffer) > MAX_OBSERVATION_BUFFER:
                self._observation_buffer.pop(0)
            if self._on_narration:
                asyncio.create_task(self._on_narration(display))

        # Parse gesture tags
        for m in GESTURE_RE.finditer(text):
            gesture = m.group(1)
            log.info(f"GESTURE: {gesture}")
            if self._on_gesture:
                asyncio.create_task(self._on_gesture(gesture))

        # Parse action tags
        for m in ACTION_RE.finditer(text):
            action_type = m.group(1)
            params_str = m.group(2)
            log.info(f"ACTION: {action_type} {params_str}")
            try:
                import json
                params = json.loads(params_str)
            except Exception:
                params = {}
            if self._on_action:
                asyncio.create_task(self._on_action(action_type, params))

    async def _watcher(self):
        """Periodically prompt Gemini to check for gestures and context."""
        await asyncio.sleep(8)
        idx = 0
        try:
            while self._running:
                if self._gemini_speaking:
                    await asyncio.sleep(1)
                    continue

                if self._watcher_paused:
                    elapsed = time.monotonic() - self._player_stopped_speaking_at
                    if self._player_stopped_speaking_at > 0 and elapsed >= WATCHER_RESUME_DELAY:
                        self._watcher_paused = False
                    else:
                        await asyncio.sleep(1)
                        continue

                prompt = WATCHER_PROMPTS[idx % len(WATCHER_PROMPTS)]

                # Add recent context
                recent = self._observation_buffer[-3:]
                if recent:
                    context = "Recent context: " + " | ".join(recent)
                    prompt = f"{context}\n\n{prompt}"

                log.info("Watcher check: %s", prompt[:100])
                try:
                    await self._session.send_client_content(
                        turns=types.Content(
                            role="user",
                            parts=[types.Part(text=prompt)],
                        ),
                        turn_complete=True,
                    )
                except Exception as e:
                    log.error(f"Watcher error: {e}")
                idx += 1

                interval = WATCHER_ACTIVE_INTERVAL if self._user_interacted else WATCHER_IDLE_INTERVAL
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
