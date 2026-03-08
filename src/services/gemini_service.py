"""Gemini Live API service with VAD — personal assistant mode."""

import asyncio
import json
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
    WATCHER_INTERVAL,
    WATCHER_RESUME_DELAY,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are SILAS — a smart personal assistant that sees and hears through the user's phone.

PERSONALITY: Calm, efficient, helpful. Concise and clear.
ONE sentence replies, two max. No fluff.

─── WHAT YOU SEE AND HEAR ─────────────────────────────────
The user holds their phone with the REAR camera facing outward.
You see what's IN FRONT of the user. You CANNOT see the user themselves.
You hear the user's microphone — their voice and ambient audio.

─── HOW IT WORKS ──────────────────────────────────────────
GESTURES trigger actions (the "what to do").
VOICE provides content (the "what to do it with").

Example flows:
1. User shows OPEN PALM → you emit <<GESTURE open_palm>> → system prompts user
   → user says "remember to buy groceries" → you emit <<ACTION note {"content": "remember to buy groceries"}>>
2. User shows WAVE → you emit <<GESTURE wave>> → meeting minutes start recording
3. User says "take a note, call dentist at 3pm" → you emit <<ACTION note {"content": "call dentist at 3pm"}>>

Voice commands work WITHOUT gestures too. If the user asks you to do something
verbally, emit the <<ACTION>> tag directly.

─── GESTURE RECOGNITION (CRITICAL) ────────────────────────
You MUST actively watch every video frame for hand gestures.
The user will hold up their hand in front of the camera.

WHAT GESTURES LOOK LIKE IN THE CAMERA:
• THUMBS UP — a fist with thumb extended upward.
• OPEN PALM — all five fingers spread wide, palm facing camera.
• PEACE SIGN — a fist with index and middle fingers extended in a V shape.
• POINTING UP — a fist with only the index finger extended straight up.
• WAVE — an open hand moving side to side.
• OK SIGN — thumb and index finger forming a circle, other fingers extended.

When you see a hand gesture, emit <<GESTURE gesture_name>> immediately.
Do NOT wait. Do NOT second-guess. Tag it.

─── TAGS ──────────────────────────────────────────────────
Emit as TEXT on their own line:

<<GESTURE gesture_name>>
gesture_name: thumbs_up, open_palm, peace_sign, point_up, wave, ok_sign

<<ACTION action_type json_params>>
Emit when the user provides voice content for an action:

  note — params: {"content": "the note text"}
  meeting_minutes — params: {"command": "start"} or {"command": "stop"}
  draft_email — params: {"to": "recipient", "subject": "subject", "body": "body"}
  send_email — params: {}
  read_email — params: {"count": 5}
  calendar_event — params: {"title": "title", "start": "ISO datetime", "duration_minutes": 30, "description": ""}

RULES:
- NEVER announce tags aloud. Tags are silent metadata.
- After a gesture is detected, the system will ask the user for voice input.
  Listen for their spoken content and emit the <<ACTION>> tag with the details.
- For voice-only commands (no gesture), emit <<ACTION>> directly.
- When told "GESTURE CHECK", look at the current video frame for hand gestures.
  If you see one, emit the tag. If not, respond with just "clear"."""

GESTURE_RE = re.compile(r"<<GESTURE\s+(\w+)>>")
ACTION_RE = re.compile(r"<<ACTION\s+(\w+)\s+(\{.*?\})>>", re.DOTALL)

# Watcher prompts — very explicit about looking for hands
WATCHER_PROMPTS = [
    "GESTURE CHECK. Look at the video frame RIGHT NOW. Do you see a hand, fingers, or any gesture? If yes, emit <<GESTURE>> tag. If no hand visible, say 'clear'.",
    "GESTURE CHECK. Scan the current frame for hands. Thumbs up? Open palm? Peace sign? Pointing? Any hand shape at all? Tag it or say 'clear'.",
    "GESTURE CHECK. Is there a hand or fingers visible in the frame? Describe what you see briefly, and emit <<GESTURE>> if it matches any known gesture.",
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
        self._user_stopped_speaking_at = 0.0
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
            response_modalities=["AUDIO", "TEXT"],
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

    async def start_session(self):
        """Connect to Gemini and start watching for gestures immediately."""
        log.info("Connecting to Gemini Live API...")
        self._observation_buffer.clear()
        config = self._build_live_config()
        self._ctx = self._client.aio.live.connect(
            model=GEMINI_MODEL, config=config,
        )
        self._session = await self._ctx.__aenter__()
        self._running = True
        log.info("Connected to Gemini (voice=%s)", GEMINI_VOICE)

        # Start receive loop
        self._receive_task = asyncio.create_task(self._receive_loop())

        # Send session start prompt — no intro, straight to work
        await self._session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=(
                    "Session active. You are Silas, the user's personal assistant. "
                    "Watch the video feed for hand gestures and listen for voice commands. "
                    "Emit <<GESTURE>> and <<ACTION>> tags as TEXT when you detect them. "
                    "Say a very brief greeting (one sentence) and start watching."
                ))],
            ),
            turn_complete=True,
        )
        log.info("Session started — watching for gestures and commands")

        # Start gesture watcher
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

    async def send_prompt(self, text: str):
        """Send a text prompt to Gemini (e.g., to ask the user for voice input)."""
        if not self._session or not self._running:
            return
        try:
            await self._session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=f"Say this to the user: \"{text}\"")],
                ),
                turn_complete=True,
            )
        except Exception as e:
            log.error(f"Error sending prompt: {e}")

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
                self._user_stopped_speaking_at = now
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
                                    log.info("Gemini text: %s", text_buf.strip()[:200])
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
        # Strip tags for display narration
        display = GESTURE_RE.sub("", text)
        display = ACTION_RE.sub("", display).strip()
        # Filter out "clear" responses from watcher
        if display and display.lower() not in ("clear", "clear."):
            log.info("NARRATION (trigger=%s): %s", trigger, display)
            self._observation_buffer.append(display)
            if len(self._observation_buffer) > MAX_OBSERVATION_BUFFER:
                self._observation_buffer.pop(0)
            if self._on_narration:
                asyncio.create_task(self._on_narration(display))

        # Parse gesture tags
        for m in GESTURE_RE.finditer(text):
            gesture = m.group(1)
            log.info(f"GESTURE DETECTED: {gesture}")
            if self._on_gesture:
                asyncio.create_task(self._on_gesture(gesture))

        # Parse action tags
        for m in ACTION_RE.finditer(text):
            action_type = m.group(1)
            params_str = m.group(2)
            log.info(f"ACTION: {action_type} {params_str}")
            try:
                params = json.loads(params_str)
            except Exception:
                params = {}
            if self._on_action:
                asyncio.create_task(self._on_action(action_type, params))

    async def _watcher(self):
        """Frequently prompt Gemini to check for hand gestures in the video."""
        await asyncio.sleep(3)  # short initial delay
        idx = 0
        try:
            while self._running:
                if self._gemini_speaking:
                    await asyncio.sleep(1)
                    continue

                if self._watcher_paused:
                    elapsed = time.monotonic() - self._user_stopped_speaking_at
                    if self._user_stopped_speaking_at > 0 and elapsed >= WATCHER_RESUME_DELAY:
                        self._watcher_paused = False
                    else:
                        await asyncio.sleep(1)
                        continue

                prompt = WATCHER_PROMPTS[idx % len(WATCHER_PROMPTS)]

                log.info("Watcher: gesture check #%d", idx + 1)
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

                await asyncio.sleep(WATCHER_INTERVAL)
        except asyncio.CancelledError:
            pass
