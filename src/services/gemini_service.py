"""Gemini Live API service with VAD — personal assistant mode.

Gesture detection via speech: Gemini speaks gesture/action cues aloud,
and we parse them from the narration text (since native audio model
does not output text tags).
"""

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
    WATCHER_INTERVAL,
    WATCHER_RESUME_DELAY,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are SILAS — a concise personal assistant. You see via phone camera and hear via mic.

CRITICAL RULES:
1. NEVER think out loud. No "analyzing", "scanning", "I see", "let me check".
2. When you see a gesture, say ONLY "GESTURE: <name>" — nothing else.
3. When no gesture is visible and you get a GESTURE CHECK, produce NO output. Stay completely silent. Do NOT say anything.
4. Keep ALL replies to ONE short sentence. No explanations.

─── CAMERA ────────────────────────────────────────────────
Rear camera faces outward — you see what's in front of the user.

─── GESTURES ──────────────────────────────────────────────
Watch for hand gestures in every frame:
• THUMBS UP — fist with thumb up
• OPEN PALM — five fingers spread, palm facing camera
• PEACE SIGN — index + middle fingers in V
• POINTING UP — only index finger extended up
• WAVE — open hand moving side to side
• OK SIGN — thumb + index forming a circle

When you see one → say "GESTURE: <name>" (e.g. "GESTURE: thumbs up")
When you DON'T see one → say absolutely nothing.

─── VOICE COMMANDS ────────────────────────────────────────
When user speaks a command, say "ACTION: <type>" with details:
• "ACTION: note start." — user says "take note" or "start note"
• "ACTION: note stop." — user says "note end", "stop note", or "done"
• "ACTION: note. Buy groceries." — quick one-shot note
• "ACTION: draft email. To John, subject update, body let's meet Friday."
• "ACTION: calendar event. Standup tomorrow 10am."
• "ACTION: meeting minutes start." / "ACTION: meeting minutes stop."
• "ACTION: send email." / "ACTION: read email."

IMPORTANT for notes:
- If user says "take note", "start note", "begin note" → say "ACTION: note start."
- If user says "note end", "stop note", "done with note", "that's it" → say "ACTION: note stop."
- If user says "note: buy milk" (short, all at once) → say "ACTION: note. buy milk."

Then a brief confirmation like "Got it" or "Done". Nothing more."""

# Parse spoken gesture announcements from narration text
# Matches: "gesture: open palm", "Gesture: thumbs up", etc.
SPOKEN_GESTURE_RE = re.compile(
    r"gesture:\s*(thumbs?\s*up|open\s*palm|peace\s*sign|point(?:ing)?\s*up|wave|ok\s*sign)",
    re.IGNORECASE,
)

# Parse spoken action announcements from narration text
# Matches: "action: note", "Action: draft email", "action: note start", etc.
SPOKEN_ACTION_RE = re.compile(
    r"action:\s*(note\s*(?:start|stop)|note|draft\s*email|send\s*email|read\s*email|calendar\s*event|meeting\s*minutes\s*(?:start|stop))",
    re.IGNORECASE,
)

# Normalize gesture names from speech to internal names
GESTURE_NORMALIZE = {
    "thumbs up": "thumbs_up",
    "thumb up": "thumbs_up",
    "open palm": "open_palm",
    "peace sign": "peace_sign",
    "pointing up": "point_up",
    "point up": "point_up",
    "wave": "wave",
    "ok sign": "ok_sign",
}

# Normalize action names from speech to internal names
ACTION_NORMALIZE = {
    "note": "note",
    "note start": "note_start",
    "notestart": "note_start",
    "note stop": "note_stop",
    "notestop": "note_stop",
    "draft email": "draft_email",
    "send email": "send_email",
    "read email": "read_email",
    "calendar event": "calendar_event",
    "meeting minutes start": "meeting_minutes_start",
    "meeting minutes stop": "meeting_minutes_stop",
}

WATCHER_PROMPTS = [
    "GESTURE CHECK. Hand visible? → say GESTURE: <name>. No hand? → say nothing.",
    "GESTURE CHECK. Any hand gesture in frame? If yes: GESTURE: <name>. If no: silence.",
    "GESTURE CHECK. Look for hands. Gesture → announce. No gesture → no output.",
]

MAX_RECONNECT_ATTEMPTS = 5
MAX_OBSERVATION_BUFFER = 10

# Patterns that indicate Gemini's internal reasoning (not user-facing speech)
THINKING_PATTERNS = re.compile(
    r"(?i)"
    r"(?:^|\n)\s*\*\*.*?\*\*"            # Markdown bold headers like **Analyzing...**
    r"|(?:^|\n)\s*#+\s+"                  # Markdown # headers
    r"|(?:analyzing|initiating|processing|examining|scanning|observing|checking)"
    r"\s+(?:gesture|frame|video|image|request|observation|protocol|the current)"
    r"|I(?:'ve| have)\s+(?:examined|analyzed|scanned|processed|checked|looked at)\s+(?:the|this)"
    r"|no\s+(?:hand|gesture|fingers?)(?:\s+(?:gesture|visible|detected|present|seen))"
    r"|I\s+(?:don't|do not)\s+see\s+(?:any\s+)?(?:hand|gesture|fingers?)"
    r"|nothing\s+(?:detected|visible|to report)"
    r"|the\s+frame\s+(?:shows?|contains?|appears?)"
    r"|current(?:ly)?\s+(?:frame|video|image)\s+(?:shows?|contains?)"
    r"|let me (?:check|scan|look|examine|analyze)"
    r"|gesture check(?:ing)?\s*(?:complete|done|finished)?"
)


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

        # Gesture dedup: suppress repeated same-gesture detections
        self._last_gesture: str | None = None
        self._last_gesture_time: float = 0.0
        self._gesture_dedup_window = 10.0  # seconds to suppress same gesture

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
        config_kwargs = dict(
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
        # Try to disable thinking/reasoning to reduce verbose output
        try:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=0,
            )
        except Exception:
            pass  # Not all model versions support this
        return types.LiveConnectConfig(**config_kwargs)

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

        self._receive_task = asyncio.create_task(self._receive_loop())

        await self._session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=(
                    "Session started. Say a 3-4 word greeting like 'Hey, Silas here.' "
                    "then start watching silently. Do NOT describe what you see."
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

    async def send_prompt(self, text: str):
        """Tell Gemini to speak something to the user."""
        if not self._session or not self._running:
            return
        try:
            await self._session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=(
                        f"Tell the user this in one brief sentence (paraphrase naturally, "
                        f"don't read it robotically): {text}"
                    ))],
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

                        # Audio data
                        if msg.data:
                            if not self._gemini_speaking:
                                self._gemini_speaking = True
                            if self._on_audio:
                                asyncio.create_task(self._on_audio(msg.data))

                        # Text — collect from msg.text (skip if it's thought/reasoning)
                        if msg.text and not getattr(msg, "thought", False):
                            text_buf += msg.text

                        # Check server_content for text in model_turn parts
                        if hasattr(msg, "server_content") and msg.server_content:
                            sc = msg.server_content

                            if hasattr(sc, "model_turn") and sc.model_turn:
                                for part in (sc.model_turn.parts or []):
                                    try:
                                        # Skip thought/reasoning parts
                                        if hasattr(part, "thought") and part.thought:
                                            continue
                                        if hasattr(part, "text") and part.text:
                                            if part.text not in text_buf:
                                                text_buf += part.text
                                    except Exception:
                                        pass

                            if hasattr(sc, "turn_complete") and sc.turn_complete:
                                self._gemini_speaking = False
                                if text_buf.strip():
                                    log.info("Gemini said: %s", text_buf.strip()[:300])
                                    self._parse_speech(text_buf)
                                else:
                                    log.info("Gemini turn complete (audio only, no text)")
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

    def _parse_speech(self, text: str):
        """Parse Gemini's spoken output for gesture and action announcements."""

        # Check for gesture announcements: "GESTURE: open palm"
        gesture_match = SPOKEN_GESTURE_RE.search(text)
        if gesture_match:
            raw = gesture_match.group(1).strip().lower()
            gesture = GESTURE_NORMALIZE.get(raw)
            if gesture:
                now = time.monotonic()
                # Dedup: suppress if same gesture detected within window
                if (gesture == self._last_gesture
                        and now - self._last_gesture_time < self._gesture_dedup_window):
                    log.info("GESTURE (spoken): %s → %s [DEDUP suppressed]", raw, gesture)
                else:
                    self._last_gesture = gesture
                    self._last_gesture_time = now
                    # Pause watcher after gesture detection to avoid re-triggers
                    self._watcher_paused = True
                    self._user_stopped_speaking_at = now
                    log.info("GESTURE (spoken): %s → %s", raw, gesture)
                    if self._on_gesture:
                        asyncio.create_task(self._on_gesture(gesture))

        # Check for action announcements: "ACTION: note. Buy groceries."
        action_match = SPOKEN_ACTION_RE.search(text)
        if action_match:
            raw_action = action_match.group(1).strip().lower()
            action = ACTION_NORMALIZE.get(raw_action)
            if action:
                # Extract content after the action announcement
                after = text[action_match.end():].strip().strip(".").strip()
                params = self._build_params_from_speech(action, after)
                log.info("ACTION (spoken): %s params=%s", action, params)
                if self._on_action:
                    asyncio.create_task(self._on_action(action, params))

        # Strip gesture/action prefixes from display text
        display = SPOKEN_GESTURE_RE.sub("", text)
        display = SPOKEN_ACTION_RE.sub("", display).strip()

        # Filter out Gemini's internal thinking/reasoning — only show user-facing speech
        display = self._filter_narration(display)

        if display:
            self._observation_buffer.append(display)
            if len(self._observation_buffer) > MAX_OBSERVATION_BUFFER:
                self._observation_buffer.pop(0)
            if self._on_narration:
                asyncio.create_task(self._on_narration(display))

    def _filter_narration(self, text: str) -> str:
        """Filter out Gemini's internal reasoning, keeping only user-facing speech."""
        if not text:
            return ""

        # Strip markdown formatting
        clean = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)  # **bold** → bold
        clean = re.sub(r"^\s*#+\s+", "", clean, flags=re.MULTILINE)  # # headers

        # If the whole text matches thinking patterns, suppress it entirely
        if THINKING_PATTERNS.search(clean):
            # Extract any remaining user-facing content after removing thinking parts
            lines = clean.split("\n")
            kept = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if THINKING_PATTERNS.search(line):
                    continue
                kept.append(line)
            clean = " ".join(kept).strip()

        # Strip trailing/leading whitespace and orphan punctuation
        clean = clean.strip().strip(".-—").strip()

        return clean

    def _build_params_from_speech(self, action: str, spoken_content: str) -> dict:
        """Build action params from the spoken content after an ACTION announcement."""
        if action == "note":
            return {"content": spoken_content} if spoken_content else {}
        elif action == "note_start":
            return {"command": "start"}
        elif action == "note_stop":
            return {"command": "stop"}
        elif action == "meeting_minutes_start":
            return {"command": "start"}
        elif action == "meeting_minutes_stop":
            return {"command": "stop"}
        elif action == "draft_email":
            return {"to": "", "subject": "", "body": spoken_content}
        elif action == "send_email":
            return {}
        elif action == "read_email":
            return {"count": 5}
        elif action == "calendar_event":
            return {"title": spoken_content[:60]} if spoken_content else {}
        return {}

    async def _watcher(self):
        """Periodically prompt Gemini to check for hand gestures in the video."""
        await asyncio.sleep(3)
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
