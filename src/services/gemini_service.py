"""Gemini Live API service with VAD — voice-only personal assistant.

User speaks commands, Gemini parses and announces actions via speech.
We parse action announcements from the narration text.
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
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are Modern Intern — a concise voice-only personal assistant. You hear via mic and speak via audio.

CRITICAL RULES:
1. NEVER think out loud. No "analyzing", "scanning", "let me check".
2. Keep ALL replies to ONE short sentence. No explanations.
3. Be natural and conversational, but always brief.

─── VOICE COMMANDS ────────────────────────────────────────
When user speaks a command, say "ACTION: <type>" followed by structured details.

NOTES:
• "ACTION: note start." — user says "take note" or "start note"
• "ACTION: note stop." — user says "note end", "stop note", "done"
• "ACTION: note. Buy groceries." — quick one-shot note

EMAIL (always include to/subject/body fields):
• "ACTION: draft email. to: John, subject: project update, body: let's meet Friday."
• "ACTION: send email." — sends the current draft (must have one)
• "ACTION: read email." — reads recent emails
If user says "draft email to Sarah about lunch" → "ACTION: draft email. to: Sarah, subject: lunch, body: let's grab lunch."
If user gives incomplete info like "draft email about the meeting" (no recipient) → ask "Who should I send it to?" Do NOT fire ACTION without a recipient.

CALENDAR (always include title/date/time fields):
• "ACTION: calendar event. title: standup, date: tomorrow, time: 10am, duration: 30 min, participants: team."
If user says "schedule a meeting with John tomorrow at 3pm" → "ACTION: calendar event. title: meeting, date: tomorrow, time: 3pm, participants: John."
If user gives incomplete info like "add event for lunch" (no date/time) → ask "When is the lunch event?"
NEVER fire "ACTION: calendar event" without at least a title and date/time — ask the user first.

MEETINGS:
• "ACTION: meeting minutes start." / "ACTION: meeting minutes stop."

RULES:
- For draft email: ALWAYS include "to:", "subject:", and "body:" fields.
- NEVER fire "ACTION: draft email" without a recipient — ask the user first.
- NEVER fire "ACTION: send email" if no draft exists — say "No draft to send."
- After each ACTION, say a brief confirmation. Nothing more.

─── CONVERSATION ──────────────────────────────────────────
You can also have brief natural conversations with the user.
If they ask a question, answer concisely. If they chat, be friendly but brief.
Only use ACTION: when the user gives an actual command."""

# Parse spoken action announcements from narration text
SPOKEN_ACTION_RE = re.compile(
    r"action:\s*(note\s*(?:start|stop)|note|draft\s*email|send\s*email|read\s*email|calendar\s*event|meeting\s*minutes\s*(?:start|stop))",
    re.IGNORECASE,
)

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

MAX_RECONNECT_ATTEMPTS = 5
MAX_OBSERVATION_BUFFER = 10

# Patterns that indicate Gemini's internal reasoning (not user-facing speech)
THINKING_PATTERNS = re.compile(
    r"(?i)"
    r"(?:^|\n)\s*\*\*.*?\*\*"            # Markdown bold headers
    r"|(?:^|\n)\s*#+\s+"                  # Markdown # headers
    r"|(?:analyzing|initiating|processing|examining|scanning|observing|checking)"
    r"\s+(?:request|observation|protocol|the current|input|command)"
    r"|I(?:'ve| have)\s+(?:examined|analyzed|scanned|processed|checked|looked at)\s+(?:the|this)"
    r"|nothing\s+(?:detected|visible|to report)"
    r"|let me (?:check|scan|look|examine|analyze)"
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

        # Observation buffer for context
        self._observation_buffer: list[str] = []

        # Callbacks
        self._on_audio = None
        self._on_narration = None
        self._on_action = None
        self._on_vad_state = None
        self._on_user_speech = None

        self._receive_task = None

    def set_callbacks(self, on_audio=None, on_narration=None,
                      on_action=None, on_vad_state=None, on_user_speech=None):
        self._on_audio = on_audio
        self._on_narration = on_narration
        self._on_action = on_action
        self._on_vad_state = on_vad_state
        self._on_user_speech = on_user_speech

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
            output_audio_transcription=types.AudioTranscriptionConfig(),
            input_audio_transcription=types.AudioTranscriptionConfig(),
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
            pass
        return types.LiveConnectConfig(**config_kwargs)

    async def start_session(self):
        """Connect to Gemini and start listening."""
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
                    "Session started. Say a brief greeting like 'Hey, Modern Intern here. What can I do for you?'"
                ))],
            ),
            turn_complete=True,
        )
        log.info("Session started — listening for voice commands")

    async def stop(self):
        self._running = False
        if self._receive_task:
            self._receive_task.cancel()
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

                        # Check server_content for audio, transcription, turn_complete
                        if hasattr(msg, "server_content") and msg.server_content:
                            sc = msg.server_content

                            # Audio data from model_turn
                            if hasattr(sc, "model_turn") and sc.model_turn:
                                for part in (sc.model_turn.parts or []):
                                    if hasattr(part, "inline_data") and part.inline_data:
                                        if not self._gemini_speaking:
                                            self._gemini_speaking = True
                                        if self._on_audio:
                                            asyncio.create_task(self._on_audio(part.inline_data.data))

                            # Output transcription (text of what Gemini spoke)
                            if hasattr(sc, "output_transcription") and sc.output_transcription:
                                t = getattr(sc.output_transcription, "text", "")
                                if t:
                                    text_buf += t

                            # Input transcription (text of what user said)
                            if hasattr(sc, "input_transcription") and sc.input_transcription:
                                t = getattr(sc.input_transcription, "text", "")
                                if t and t.strip() and self._on_user_speech:
                                    asyncio.create_task(self._on_user_speech(t.strip()))

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
        """Parse Gemini's spoken output for action announcements."""

        # Check for action announcements: "ACTION: note. Buy groceries."
        action_match = SPOKEN_ACTION_RE.search(text)
        if action_match:
            raw_action = action_match.group(1).strip().lower()
            action = ACTION_NORMALIZE.get(raw_action)
            if action:
                after = text[action_match.end():].strip().strip(".").strip()
                params = self._build_params_from_speech(action, after)
                log.info("ACTION (spoken): %s params=%s", action, params)
                if self._on_action:
                    asyncio.create_task(self._on_action(action, params))

        # Strip action prefix from display text
        display = SPOKEN_ACTION_RE.sub("", text).strip()

        # Filter out internal thinking
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

        clean = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
        clean = re.sub(r"^\s*#+\s+", "", clean, flags=re.MULTILINE)

        if THINKING_PATTERNS.search(clean):
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
            return self._parse_email_fields(spoken_content)
        elif action == "send_email":
            return {}
        elif action == "read_email":
            return {"count": 5}
        elif action == "calendar_event":
            return self._parse_calendar_fields(spoken_content)
        return {}

    def _parse_email_fields(self, text: str) -> dict:
        """Parse 'to: X, subject: Y, body: Z' from spoken content."""
        result = {"to": "", "subject": "", "body": ""}
        if not text:
            return result

        # Try structured parsing: "to: John, subject: update, body: let's meet"
        to_match = re.search(r"to:\s*([^,]+)", text, re.IGNORECASE)
        subj_match = re.search(r"subject:\s*([^,]+?)(?:,\s*body:|$)", text, re.IGNORECASE)
        body_match = re.search(r"body:\s*(.+)", text, re.IGNORECASE)

        if to_match:
            result["to"] = to_match.group(1).strip().rstrip(".")
        if subj_match:
            result["subject"] = subj_match.group(1).strip().rstrip(".")
        if body_match:
            result["body"] = body_match.group(1).strip().rstrip(".")

        # Fallback: if no structured fields found, dump everything as body
        if not result["to"] and not result["subject"] and not result["body"]:
            result["body"] = text

        return result

    def _parse_calendar_fields(self, text: str) -> dict:
        """Parse 'title: X, date: Y, time: Z, duration: W, participants: P' from spoken content."""
        result = {"title": "", "date": "", "time": "", "duration": "", "participants": ""}
        if not text:
            return result

        title_match = re.search(r"title:\s*([^,]+)", text, re.IGNORECASE)
        date_match = re.search(r"date:\s*([^,]+)", text, re.IGNORECASE)
        time_match = re.search(r"time:\s*([^,]+)", text, re.IGNORECASE)
        dur_match = re.search(r"duration:\s*([^,]+)", text, re.IGNORECASE)
        part_match = re.search(r"participants?:\s*(.+?)(?:,\s*(?:title|date|time|duration):|\.?$)", text, re.IGNORECASE)

        if title_match:
            result["title"] = title_match.group(1).strip().rstrip(".")
        if date_match:
            result["date"] = date_match.group(1).strip().rstrip(".")
        if time_match:
            result["time"] = time_match.group(1).strip().rstrip(".")
        if dur_match:
            result["duration"] = dur_match.group(1).strip().rstrip(".")
        if part_match:
            result["participants"] = part_match.group(1).strip().rstrip(".")

        # Fallback: if no structured fields, use whole text as title
        if not result["title"]:
            result["title"] = text.strip().rstrip(".")[:60]

        return result
