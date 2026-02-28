"""Gemini Live API service with VAD for voice chat."""

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
    NUDGE_INTERVAL,
    SPEECH_ONSET_SEC,
    SILENCE_TIMEOUT_SEC,
    VAD_AGGRESSIVENESS,
    VAD_CHUNK_SIZE,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are SILAS — the Social Intelligence Liaison and Arcane Scorekeeper.
Narrator companion for "Kindness Speedrun," an AR social game where the player
("the Alchemist") earns points by being social with strangers ("wandering souls").

PERSONALITY: Dramatic fantasy narrator meets hype-man. Witty, over-the-top,
treats handshakes like sword clashes. Keep it SHORT — 1-2 punchy sentences max.

WHEN THE GAME STARTS, say only:
"I am Silas. Your quest: turn awkward silence into social gold. Clock's ticking, Alchemist."

You receive continuous video + audio from the player's camera and mic.

RESPONSIBILITIES:
1. NARRATE in 1-2 dramatic sentences (spoken aloud, under 10 seconds)
2. DETECT social actions and embed scoring tags
3. DETECT antisocial/idle behavior and embed penalty tags
4. KEEP NARRATING every 10-15s — tease the player if nothing happens

SCORING TAGS — emit on their own line after narration:

<<SCORE action_type points description>>
action_types: greeting, introduction, laughter, compliment, helping,
high_five, sharing, group_conversation, teaching (10-30 pts)

<<PENALIZE action_type points>>
action_types: idle, phone_staring, walking_away, ignoring, prolonged_silence (5-20 pts)

<<MUSIC mood>>
moods: idle, approaching, action_scored, streak, legendary, draining,
final_minute, victory, defeat

EXAMPLES:
- "Bold. The Alchemist approaches a wandering soul."
  <<SCORE greeting 10 Player approached and greeted a stranger>>
  <<MUSIC approaching>>
- "The void stares back. Not a soul engaged."
  <<PENALIZE idle 5>>
  <<MUSIC draining>>

CRITICAL NARRATION RULES:
- NEVER say the words "penalize", "penalty", "deducted", or "points deducted" in your spoken narration.
  Instead use dramatic descriptions: "The essence fades...", "A soul withers...", "Darkness creeps in..."
- NEVER announce the tags you're emitting. Don't say "I'm scoring you" or "That's a penalty."
- Your narration should be pure STORYTELLING. Tags are silent metadata — the player sees the score
  changes on screen automatically. You just narrate the SCENE.
- Never narrate private conversation content.
- ALWAYS include at least one tag per beat.
- Be entertaining above all."""

SCORE_RE = re.compile(r"<<SCORE\s+(\w+)\s+(\d+)\s+(.+?)>>")
PENALIZE_RE = re.compile(r"<<PENALIZE\s+(\w+)\s+(\d+)>>")
MUSIC_RE = re.compile(r"<<MUSIC\s+(\w+)>>")

NUDGE_PROMPTS = [
    "Continue observing. What's happening now? Narrate and emit tags.",
    "Keep narrating, Silas. What do you see? Include scoring tags.",
    "The game continues. Observe and narrate. Don't forget the tags.",
    "Time is ticking, Silas. What's the Alchemist doing?",
    "Don't go quiet. Narrate and score what you observe.",
    "Focus on body language. Is the Alchemist open or closed off? Narrate it.",
    "Look at the environment. Who's around? Any wandering souls nearby?",
    "How's the crowd energy? Is there potential for a transmutation?",
    "Tease the Alchemist a bit. Are they being bold or timid? Narrate and tag.",
    "Give us something dramatic, Silas. What epic moment is unfolding?",
    "Comedy time. Find something funny about what's happening and narrate it.",
    "Is anyone reacting to the Alchemist? Describe the social dynamics.",
    "Rate the Alchemist's social courage right now. Narrate your judgment.",
    "Any laughter? Smiles? Awkward silences? Call it out with flair.",
    "The audience demands entertainment. Deliver a legendary narration beat.",
]

MAX_RECONNECT_ATTEMPTS = 5
MAX_OBSERVATION_BUFFER = 10

class GeminiService:
    def __init__(self, api_key: str, system_prompt: str | None = None):
        self._client = genai.Client(api_key=api_key)
        self._session = None
        self._ctx = None
        self._running = False
        self._system_prompt = system_prompt  # None = use default SYSTEM_PROMPT

        # VAD
        self._vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self._mic_state = "IDLE"
        self._gemini_speaking = False
        self._speech_start = 0.0
        self._last_speech = 0.0
        self._pending_buffer = []
        self._silence = b"\x00" * VAD_CHUNK_SIZE * 2

        # Observation buffer for multi-turn context
        self._observation_buffer: list[str] = []

        # Game state reference (set by orchestrator)
        self._game_state_fn = None

        # Callbacks
        self._on_audio = None
        self._on_narration = None
        self._on_score = None
        self._on_penalize = None
        self._on_music = None

        self._receive_task = None
        self._nudge_task = None

    def set_callbacks(self, on_audio=None, on_narration=None,
                      on_score=None, on_penalize=None, on_music=None):
        self._on_audio = on_audio
        self._on_narration = on_narration
        self._on_score = on_score
        self._on_penalize = on_penalize
        self._on_music = on_music

    def set_game_state_fn(self, fn):
        """Set a callable that returns current game state dict."""
        self._game_state_fn = fn

    @property
    def connected(self) -> bool:
        return self._session is not None and self._running

    def _build_live_config(self) -> types.LiveConnectConfig:
        """Build live config, using custom system prompt if provided."""
        prompt = self._system_prompt or SYSTEM_PROMPT
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part(text=prompt)]
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

    async def connect_and_intro(self):
        """Connect to Gemini and play the intro narration only."""
        log.info("Connecting to Gemini Live API...")
        self._observation_buffer.clear()
        config = self._build_live_config()
        self._ctx = self._client.aio.live.connect(
            model=GEMINI_MODEL, config=config,
        )
        self._session = await self._ctx.__aenter__()
        self._running = True
        log.info("Connected to Gemini (voice=%s)", GEMINI_VOICE)

        if self._system_prompt:
            # Chat mode: simple greeting
            await self._session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=(
                        "Hey! I've got my camera on. I'll talk to you when I have questions. "
                        "Keep responses short and natural. Wait for me to speak first."
                    ))],
                ),
                turn_complete=True,
            )
            log.info("Sent chat intro prompt")
        else:
            # Game mode: Silas intro
            await self._session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=(
                        "Introduce yourself as Silas in one dramatic sentence. "
                        "Do NOT emit any scoring tags yet — just the intro."
                    ))],
                ),
                turn_complete=True,
            )
            log.info("Sent intro prompt (trigger=intro)")

        self._receive_task = asyncio.create_task(self._receive_loop())

    async def begin_game(self):
        """Start the game loop — nudger + game-start prompt.

        Assumes connect_and_intro() was already called.
        If not connected yet, does a full connect first.
        """
        if not self.connected:
            await self.connect_and_intro()
            await asyncio.sleep(1)

        await self._session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=(
                    "The game is starting NOW. Begin observing the video feed "
                    "and narrating. Include <<SCORE>>, <<PENALIZE>>, and "
                    "<<MUSIC>> tags in your text output. Go!"
                ))],
            ),
            turn_complete=True,
        )
        log.info("Sent game_start prompt (trigger=game_start)")

        self._nudge_task = asyncio.create_task(self._nudger())

    async def start(self):
        """Full start: connect + intro + begin game (legacy/terminal use)."""
        await self.connect_and_intro()
        await asyncio.sleep(1)
        await self.begin_game()

    async def stop(self):
        self._running = False
        for task in (self._receive_task, self._nudge_task):
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

    async def send_mic_audio(self, pcm_data: bytes):
        """Process mic audio through 3-state VAD FSM and forward to Gemini."""
        if not self._session or not self._running:
            return

        now = time.monotonic()

        try:
            is_speech = self._vad.is_speech(pcm_data, MIC_SAMPLE_RATE)
        except Exception:
            is_speech = False

        # Mute while Gemini is speaking
        if self._gemini_speaking:
            await self._send_silence()
            if self._mic_state != "IDLE":
                self._pending_buffer = []
                self._mic_state = "IDLE"
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

    async def inject_narration(self, text: str):
        """Inject text as if Gemini said it — for terminal testing."""
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

                    # If receive() ends cleanly, reset error count
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
                        log.warning(
                            "Gemini disconnected after %d errors, "
                            "attempting full reconnect...",
                            consecutive_errors,
                        )
                        await self._reconnect()
                        consecutive_errors = 0
                    else:
                        await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    async def _reconnect(self):
        """Close and reopen the Gemini WebSocket session."""
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
        # Clean narration text
        display = SCORE_RE.sub("", text)
        display = PENALIZE_RE.sub("", display)
        display = MUSIC_RE.sub("", display).strip()
        if display:
            log.info("NARRATION (trigger=%s): %s", trigger, display)
            # Store in observation buffer
            self._observation_buffer.append(display)
            if len(self._observation_buffer) > MAX_OBSERVATION_BUFFER:
                self._observation_buffer.pop(0)
            if self._on_narration:
                asyncio.create_task(self._on_narration(display))

        for m in SCORE_RE.finditer(text):
            action, pts, desc = m.group(1), int(m.group(2)), m.group(3)
            log.info(f"SCORE: {action} +{pts} -- {desc}")
            if self._on_score:
                asyncio.create_task(self._on_score(action, pts, desc))

        for m in PENALIZE_RE.finditer(text):
            action, pts = m.group(1), int(m.group(2))
            log.info(f"PENALIZE: {action} -{pts}")
            if self._on_penalize:
                asyncio.create_task(self._on_penalize(action, pts))

        for m in MUSIC_RE.finditer(text):
            mood = m.group(1)
            log.info(f"MUSIC: {mood}")
            if self._on_music:
                asyncio.create_task(self._on_music(mood))

    def _build_nudge_context(self) -> str:
        """Build context string with recent observations and game state."""
        parts = []

        # Recent observations
        recent = self._observation_buffer[-3:]
        if recent:
            parts.append(
                "Recent observations: "
                + " | ".join(recent)
            )

        # Game state
        if self._game_state_fn:
            state = self._game_state_fn()
            parts.append(
                f"Game state: score={state.get('essence', 0)}, "
                f"streak={state.get('streak', 0)}, "
                f"multiplier={state.get('multiplier', 1)}x, "
                f"time_left={state.get('timer', '?')}s, "
                f"rank={state.get('rank', '?')}"
            )

        return "\n".join(parts)

    async def _nudger(self):
        await asyncio.sleep(20)
        idx = 0
        try:
            while self._running:
                prompt = NUDGE_PROMPTS[idx % len(NUDGE_PROMPTS)]
                context = self._build_nudge_context()
                if context:
                    full_prompt = f"{context}\n\n{prompt}"
                else:
                    full_prompt = prompt

                log.info("Nudge (trigger=nudge): %s", full_prompt)
                try:
                    await self._session.send_client_content(
                        turns=types.Content(
                            role="user",
                            parts=[types.Part(text=full_prompt)],
                        ),
                        turn_complete=True,
                    )
                except Exception as e:
                    log.error(f"Nudge error: {e}")
                idx += 1
                await asyncio.sleep(NUDGE_INTERVAL)
        except asyncio.CancelledError:
            pass
