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
    NUDGE_ACTIVE_INTERVAL,
    NUDGE_FINAL_MINUTE_INTERVAL,
    NUDGE_IDLE_INTERVAL,
    NUDGE_POST_TASK_DELAY,
    NUDGE_RESUME_DELAY,
    SPEECH_ONSET_SEC,
    SILENCE_TIMEOUT_SEC,
    VAD_AGGRESSIVENESS,
    VAD_CHUNK_SIZE,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are SILAS — the player's friend and wingman in "JOYBAIT,"
an AR game where the player earns vibes by being social with strangers.

PERSONALITY: Chill, warm, quick. Talk like a real friend — natural, not forced.
Light slang is fine but don't overdo it. ONE sentence replies, two max.
Never sound like a narrator, announcer, or NPC.

You receive continuous video + audio from the player's camera and mic.

─── CONVERSATION (your main job) ──────────────────────────────
When the player speaks to you, RESPOND. You're their friend.
1. Reply as Silas — natural, brief, ONE sentence preferred
2. Supportive and fun, not over-the-top
3. If they ask about the game, give quick tips
4. If their speech involves a social action, include a scoring tag
5. After responding, go QUIET — wait for them to speak again

─── SCOREKEEPER (background, silent) ──────────────────────────
You will receive periodic check-in prompts asking you to observe the scene.
- If a prompt says "TAGS ONLY": respond ONLY with scoring tags.
  Do NOT speak, do NOT narrate. Just emit the tags as text.
  Example response: <<PENALIZE idle 5>>
- If a prompt says to check in: give ONE short sentence + tags.

SCORING TAGS — emit on their own line:

<<SCORE action_type points description>>
action_types: greeting, introduction, laughter, compliment, helping,
high_five, sharing, group_conversation, teaching (10-30 pts)

<<PENALIZE action_type points>>
action_types: idle, phone_staring, walking_away, ignoring, prolonged_silence (5-20 pts)

<<MUSIC mood>>
moods: idle, approaching, action_scored, streak, legendary, draining,
final_minute, victory, defeat

<<TASK task_description bonus_points>>
Assign mini-challenges to keep the player engaged. Examples:
"compliment someone's outfit" 15, "give a stranger a high five" 20,
"start a convo with someone new" 25, "make someone laugh" 20.
Drop a task when the player seems idle or needs motivation.

RULES:
- NEVER say "penalize", "penalty", or "points deducted" aloud.
- NEVER announce tags. Don't say "I'm scoring you."
- Tags are silent metadata — the player sees score changes on screen.
- Never narrate private conversation content.
- When told "TAGS ONLY", emit ONLY tags with zero spoken words.
- Keep it natural. No announcer energy."""

SCORE_RE = re.compile(r"<<SCORE\s+(\w+)\s+(\d+)\s+(.+?)>>")
PENALIZE_RE = re.compile(r"<<PENALIZE\s+(\w+)\s+(\d+)>>")
MUSIC_RE = re.compile(r"<<MUSIC\s+(\w+)>>")
TASK_RE = re.compile(r"<<TASK\s+(.+?)\s+(\d+)>>")

# Narration nudges — used before the player has spoken (narrator mode)
NARRATE_PROMPTS = [
    "check in — what's happening? score or penalize. drop a task if needed.",
    "quick look — talking to anyone? tag it. task if idle.",
    "any social moves? score or penalize accordingly. task if they need a push.",
    "check-in: social or idle? tag it. suggest a task if they're stuck.",
]

# Silent tag-only nudges — used once the player is interacting (conversation mode)
TAGS_ONLY_PROMPTS = [
    "TAGS ONLY. score or penalize. task if idle. no talking.",
    "TAGS ONLY. observe and tag. say nothing.",
    "TAGS ONLY. social or idle? emit tags. no words.",
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

        # Nudger-pause state
        self._nudger_paused = False
        self._player_stopped_speaking_at = 0.0
        self._player_interacted = False  # True once player has spoken at least once

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
        self._on_task = None
        self._on_vad_state = None

        self._receive_task = None
        self._nudge_task = None

        # Game Brain reference (set by orchestrator)
        self._brain = None

        # Track last score time for adaptive nudge intervals
        self._last_score_time = 0.0

    def set_callbacks(self, on_audio=None, on_narration=None,
                      on_score=None, on_penalize=None, on_music=None,
                      on_task=None, on_vad_state=None):
        self._on_audio = on_audio
        self._on_narration = on_narration
        self._on_score = on_score
        self._on_penalize = on_penalize
        self._on_music = on_music
        self._on_task = on_task
        self._on_vad_state = on_vad_state

    def set_game_state_fn(self, fn):
        """Set a callable that returns current game state dict."""
        self._game_state_fn = fn

    def set_brain(self, brain):
        """Set the GameBrainService reference for contextual nudges and reconnect."""
        self._brain = brain

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

        await self._session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=(
                    "Introduce yourself as Silas in one short sentence. "
                    "Chill and friendly. No scoring tags yet — just the intro."
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
                    "and vibing. Include <<SCORE>>, <<PENALIZE>>, <<MUSIC>>, "
                    "and <<TASK>> tags in your text output. Go!"
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

    def _fire_vad_state(self, state: str):
        """Fire VAD state callback if registered."""
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

        # Mute while Gemini is speaking
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
                    # Pause the nudger while player is speaking
                    self._nudger_paused = True
                    if not self._player_interacted:
                        self._player_interacted = True
                        log.info("Player interacted — nudger switching to tags-only mode")
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
                # Record when player stopped speaking for nudger resume delay
                self._player_stopped_speaking_at = now
                # Signal Gemini that the player finished speaking
                asyncio.create_task(self._signal_player_done())

        # Fire VAD state callback on state change
        if self._mic_state != prev_state:
            self._fire_vad_state(self._mic_state)

    async def _signal_player_done(self):
        """Send lightweight turn-complete signal after the player stops speaking.

        The Live API already has the audio context so we just nudge it to
        respond rather than injecting redundant text instructions.
        """
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
            log.info("Sent player-done signal (trigger=player_speech)")
        except Exception as e:
            log.error(f"Error sending player-done signal: {e}")

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
        """Close and reopen the Gemini WebSocket session with context restoration."""
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

            # Restore context from Game Brain if available
            if self._brain:
                try:
                    context = await self._brain.get_restoration_context()
                    await self._session.send_client_content(
                        turns=types.Content(
                            role="user",
                            parts=[types.Part(text=(
                                f"Session restored. Continue the game seamlessly.\n\n"
                                f"Context from before disconnect:\n{context}"
                            ))],
                        ),
                        turn_complete=True,
                    )
                    log.info("Restored game context via Game Brain after reconnect")
                except Exception as ce:
                    log.error("Context restoration failed: %s", ce)

        except Exception as e:
            log.error("Gemini reconnect failed: %s", e)
            await asyncio.sleep(5.0)

    def _parse_and_dispatch(self, text: str, trigger: str = "unknown"):
        # Clean narration text (strip tags for display)
        display = SCORE_RE.sub("", text)
        display = PENALIZE_RE.sub("", display)
        display = MUSIC_RE.sub("", display)
        display = TASK_RE.sub("", display).strip()
        if display:
            log.info("NARRATION (trigger=%s): %s", trigger, display)
            # Store in observation buffer
            self._observation_buffer.append(display)
            if len(self._observation_buffer) > MAX_OBSERVATION_BUFFER:
                self._observation_buffer.pop(0)
            if self._on_narration:
                asyncio.create_task(self._on_narration(display))

        # Live API tags kept as fallback scoring path
        for m in SCORE_RE.finditer(text):
            action, pts, desc = m.group(1), int(m.group(2)), m.group(3)
            log.info(f"SCORE (live-api): {action} +{pts} -- {desc}")
            self._last_score_time = time.monotonic()
            if self._on_score:
                asyncio.create_task(self._on_score(action, pts, desc))

        for m in PENALIZE_RE.finditer(text):
            action, pts = m.group(1), int(m.group(2))
            log.info(f"PENALIZE (live-api): {action} -{pts}")
            if self._on_penalize:
                asyncio.create_task(self._on_penalize(action, pts))

        for m in MUSIC_RE.finditer(text):
            mood = m.group(1)
            log.info(f"MUSIC (live-api): {mood}")
            if self._on_music:
                asyncio.create_task(self._on_music(mood))

        for m in TASK_RE.finditer(text):
            task_desc, bonus = m.group(1), int(m.group(2))
            log.info(f"TASK (live-api): {task_desc} +{bonus} bonus")
            if self._on_task:
                asyncio.create_task(self._on_task(task_desc, bonus))

    def _build_nudge_context(self) -> str:
        """Build context string with brain summary + game state."""
        parts = []

        # Use brain context if available (richer than raw observation buffer)
        if self._brain:
            brain_ctx = self._brain.get_context_summary()
            if brain_ctx:
                parts.append(f"Game memory: {brain_ctx}")

        # Fallback to raw observation buffer
        if not parts:
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
                f"Game state: vibes={state.get('vibes', 0)}, "
                f"streak={state.get('streak', 0)}, "
                f"multiplier={state.get('multiplier', 1)}x, "
                f"time_left={state.get('timer', '?')}s, "
                f"rank={state.get('rank', '?')}"
            )

        return "\n".join(parts)

    def _compute_nudge_interval(self) -> float:
        """Compute adaptive nudge interval based on game state."""
        now = time.monotonic()
        idle_duration = now - self._last_score_time if self._last_score_time else 0

        # Check game state for timer
        if self._game_state_fn:
            state = self._game_state_fn()
            timer = state.get("timer", 999)
            if timer <= 60:
                return NUDGE_FINAL_MINUTE_INTERVAL

        # Adaptive: shorter interval when idle, longer when active
        if idle_duration > 15:
            return NUDGE_IDLE_INTERVAL
        elif self._player_interacted:
            return NUDGE_ACTIVE_INTERVAL
        else:
            return NUDGE_IDLE_INTERVAL

    async def _nudger(self):
        await asyncio.sleep(12)
        idx = 0
        try:
            while self._running:
                # Skip nudging while Gemini is speaking (defensive guard)
                if self._gemini_speaking:
                    await asyncio.sleep(1)
                    continue

                # If nudger is paused (player was speaking), poll until resume delay elapses
                if self._nudger_paused:
                    elapsed = time.monotonic() - self._player_stopped_speaking_at
                    if self._player_stopped_speaking_at > 0 and elapsed >= NUDGE_RESUME_DELAY:
                        self._nudger_paused = False
                        log.info("Nudger resumed after player speech")
                    else:
                        await asyncio.sleep(1)
                        continue

                # Try to get a contextual nudge from the brain
                full_prompt = None
                if self._brain:
                    idle_dur = time.monotonic() - self._last_score_time if self._last_score_time else 0
                    try:
                        nudge_result = await self._brain.generate_nudge(
                            player_interacted=self._player_interacted,
                            idle_duration=idle_dur,
                        )
                        if nudge_result and nudge_result.get("prompt"):
                            full_prompt = nudge_result["prompt"]
                            if nudge_result.get("tags_only"):
                                full_prompt = f"TAGS ONLY. {full_prompt}"
                    except Exception as e:
                        log.error(f"Brain nudge generation failed: {e}")

                # Fallback to static prompts if brain didn't produce one
                if not full_prompt:
                    prompts = TAGS_ONLY_PROMPTS if self._player_interacted else NARRATE_PROMPTS
                    prompt = prompts[idx % len(prompts)]
                    context = self._build_nudge_context()
                    full_prompt = f"{context}\n\n{prompt}" if context else prompt

                log.info("Nudge (trigger=nudge): %s", full_prompt[:120])
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
                interval = self._compute_nudge_interval()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
