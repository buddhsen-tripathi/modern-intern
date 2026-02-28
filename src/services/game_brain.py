"""Game Brain — long-context Flash model for game memory and scoring decisions."""

import asyncio
import json
import logging
import time
from typing import Optional

from google import genai
from google.genai import types

from src.config import BRAIN_MAX_HISTORY, BRAIN_MODEL, BRAIN_UPDATE_INTERVAL

log = logging.getLogger(__name__)

BRAIN_SYSTEM_PROMPT = """\
You are the Game Brain for "JOYBAIT," a real-time social game.
You maintain structured memory of everything happening in the game session.

CAMERA PERSPECTIVE:
The player holds their phone with the REAR camera facing outward. The video feed
shows what is IN FRONT of the player — surroundings, other people, the environment.
The player themselves are NEVER visible in the video. The microphone captures the
player's voice and ambient audio (other people talking, laughter, background noise).

To determine what the player is doing, combine:
• AUDIO cues — player's voice greeting, conversing, laughing, complimenting
• VISUAL cues — people visible in frame, faces, reactions, proximity changes
• CONTEXT — camera moving toward people = approaching; conversation audio = engaging;
  static empty scene + silence = idle

Your responsibilities:
1. TRACK all player interactions — who they talked to (inferred from audio + scene),
   what happened, outcomes
2. SCORE social actions by combining audio evidence with visual scene context
3. GENERATE contextual nudge prompts based on game state and player patterns
4. MAINTAIN a social graph of people the player has interacted with (identified by
   appearance/description since you see their faces from the outward camera)
5. PROVIDE context restoration summaries after session reconnects

You always respond in valid JSON matching the requested schema. Never include
markdown fencing or extra text outside the JSON.

SCORING RULES:
- Positive actions (10-30 pts): greeting, introduction, laughter, compliment,
  helping, high_five, sharing, group_conversation, teaching
  Score these based on AUDIO (player speaking, laughing) + VISUAL (people nearby,
  reactions visible in frame).
- Penalties (5-20 pts): idle, avoiding_people, walking_away, ignoring, prolonged_silence
  Do NOT penalize "phone_staring" — the player holds the phone to play the game.
  "avoiding_people" = people visible in scene but no engagement audio from player.
- Music moods: idle, approaching, action_scored, streak, legendary, draining,
  final_minute, victory, defeat
- Tasks: mini-challenges to keep the player engaged (5-30 bonus pts).
  Tasks should be audio-verifiable (e.g. "say hi to someone" not "smile at someone").

Be accurate and conservative with scoring. Only score actions you can verify
through audio and/or visual scene evidence.
"""

SCORE_ANALYSIS_PROMPT = """\
Analyze these recent observations from the game and return scoring decisions.

Remember: the camera faces OUTWARD (rear camera). Observations describe what the
player sees in front of them and what is heard on their mic. The player is NOT
visible. Infer player actions from audio cues + scene context.

Current game state:
{game_state}

Recent observations (newest first):
{observations}

Player interaction history summary:
{history_summary}

Respond with ONLY valid JSON:
{{
  "scores": [
    {{"action": "action_type", "points": N, "description": "what happened"}}
  ],
  "penalties": [
    {{"action": "action_type", "points": N}}
  ],
  "mood": "mood_name or null if no change needed",
  "task": {{"text": "task description", "bonus": N}} or null,
  "observations_summary": "1-2 sentence summary of what just happened"
}}

Return empty arrays if no scoring events detected. Be conservative — only
score actions verifiable through audio evidence and/or visual scene context.
Tasks should be audio-verifiable (speak, ask, tell, laugh — not smile, wave, gesture).
"""

NUDGE_GENERATION_PROMPT = """\
Generate a contextual nudge prompt for the game's AI narrator (Silas).

Remember: Silas sees the outward-facing rear camera (surroundings, other people)
and hears the player's mic. The player is NOT visible. Nudges should reference
what can be SEEN (people, places) and HEARD (voices, conversation, silence).

Current game state:
{game_state}

Player interaction history:
{history_summary}

Current situation:
{situation}

Player has interacted at least once: {player_interacted}
Time since last score: {idle_duration}s

Generate a nudge that Silas should act on. If the player has been idle,
suggest specific actions referencing people or opportunities visible in the scene.
If active, keep it brief. Tasks should be audio-verifiable (speak, ask, laugh —
not gesture, wave, smile).

Respond with ONLY valid JSON:
{{
  "prompt": "the nudge text for Silas",
  "tags_only": true/false,
  "suggested_interval": N (seconds until next nudge)
}}
"""

CONTEXT_RESTORE_PROMPT = """\
Provide a full context restoration summary for a reconnected game session.

Full game history:
{full_history}

Current game state:
{game_state}

Respond with ONLY valid JSON:
{{
  "restoration_prompt": "A detailed paragraph summarizing everything that happened
  in this game session so far, suitable for injecting into a fresh AI session so
  it can continue seamlessly. Include: who the player talked to, key moments,
  current score trajectory, and what was happening right before the disconnect."
}}
"""


class GameEvent:
    """A single timestamped game event."""

    __slots__ = ("timestamp", "event_type", "data")

    def __init__(self, event_type: str, data: dict):
        self.timestamp = time.monotonic()
        self.event_type = event_type
        self.data = data

    def to_dict(self) -> dict:
        return {
            "elapsed": round(self.timestamp - _session_start, 1),
            "type": self.event_type,
            **self.data,
        }


# Module-level session start time, set when brain starts
_session_start: float = 0.0


class GameBrainService:
    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)
        self._running = False

        # Rolling event history
        self._history: list[GameEvent] = []

        # Pending observations from Live API (raw narration text, scene descriptions)
        self._pending_observations: list[str] = []

        # Structured summaries
        self._history_summary: str = "No interactions yet."
        self._social_graph: dict[str, list[str]] = {}  # person_desc -> [interactions]

        # Background sync task
        self._sync_task: Optional[asyncio.Task] = None

        # Callbacks
        self._on_score = None
        self._on_penalize = None
        self._on_music = None
        self._on_task = None

        # Game state reference
        self._game_state_fn = None

        # Last scoring analysis time
        self._last_analysis_time = 0.0

    def set_callbacks(self, on_score=None, on_penalize=None, on_music=None, on_task=None):
        self._on_score = on_score
        self._on_penalize = on_penalize
        self._on_music = on_music
        self._on_task = on_task

    def set_game_state_fn(self, fn):
        self._game_state_fn = fn

    def start(self):
        global _session_start
        _session_start = time.monotonic()
        self._running = True
        self._history.clear()
        self._pending_observations.clear()
        self._history_summary = "No interactions yet."
        self._social_graph.clear()
        self._last_analysis_time = time.monotonic()
        self._sync_task = asyncio.create_task(self._sync_loop())
        log.info("Game Brain started (model=%s)", BRAIN_MODEL)

    async def stop(self):
        self._running = False
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

    # -- Event recording (called by orchestrator) --

    def record_observation(self, text: str):
        """Record a raw observation from the Live API narration."""
        self._pending_observations.append(text)
        self._history.append(GameEvent("observation", {"text": text}))
        self._trim_history()

    def record_score(self, action: str, points: int, description: str):
        self._history.append(GameEvent("score", {
            "action": action, "points": points, "description": description,
        }))
        self._trim_history()

    def record_penalty(self, action: str, points: int):
        self._history.append(GameEvent("penalty", {
            "action": action, "points": points,
        }))
        self._trim_history()

    def record_mood_change(self, mood: str):
        self._history.append(GameEvent("mood_change", {"mood": mood}))
        self._trim_history()

    def record_task(self, text: str, bonus: int):
        self._history.append(GameEvent("task_assigned", {
            "text": text, "bonus": bonus,
        }))
        self._trim_history()

    def record_player_speech(self):
        self._history.append(GameEvent("player_speech", {}))
        self._trim_history()

    def _trim_history(self):
        if len(self._history) > BRAIN_MAX_HISTORY:
            self._history = self._history[-BRAIN_MAX_HISTORY:]

    # -- Scoring analysis (called periodically or on-demand) --

    async def analyze_and_score(self) -> Optional[dict]:
        """Analyze pending observations and return scoring decisions."""
        if not self._pending_observations:
            return None

        observations = list(self._pending_observations)
        self._pending_observations.clear()

        game_state = self._game_state_fn() if self._game_state_fn else {}

        prompt = SCORE_ANALYSIS_PROMPT.format(
            game_state=json.dumps(game_state, indent=2),
            observations="\n".join(f"- {o}" for o in reversed(observations)),
            history_summary=self._history_summary,
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=BRAIN_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=BRAIN_SYSTEM_PROMPT,
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )

            result = json.loads(response.text)
            self._last_analysis_time = time.monotonic()

            # Update history summary from brain's analysis
            if result.get("observations_summary"):
                self._history_summary = result["observations_summary"]

            # Dispatch scoring events
            await self._dispatch_scoring(result)

            return result

        except Exception as e:
            log.error("Game Brain analysis error: %s", e)
            # Put observations back so they aren't lost
            self._pending_observations = observations + self._pending_observations
            return None

    async def _dispatch_scoring(self, result: dict):
        """Dispatch scoring decisions from brain analysis to game state."""
        for score in result.get("scores", []):
            if self._on_score:
                await self._on_score(
                    score["action"],
                    score["points"],
                    score.get("description", ""),
                )

        for penalty in result.get("penalties", []):
            if self._on_penalize:
                await self._on_penalize(penalty["action"], penalty["points"])

        mood = result.get("mood")
        if mood and self._on_music:
            await self._on_music(mood)

        task = result.get("task")
        if task and self._on_task:
            await self._on_task(task["text"], task["bonus"])

    # -- Nudge generation --

    async def generate_nudge(self, player_interacted: bool, idle_duration: float) -> Optional[dict]:
        """Generate a contextual nudge prompt for the Live API narrator."""
        game_state = self._game_state_fn() if self._game_state_fn else {}

        # Build situation from recent observations
        recent = [e for e in self._history[-5:] if e.event_type == "observation"]
        situation = "\n".join(f"- {e.data['text']}" for e in recent) or "No recent observations."

        prompt = NUDGE_GENERATION_PROMPT.format(
            game_state=json.dumps(game_state, indent=2),
            history_summary=self._history_summary,
            situation=situation,
            player_interacted=player_interacted,
            idle_duration=round(idle_duration, 1),
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=BRAIN_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=BRAIN_SYSTEM_PROMPT,
                    temperature=0.5,
                    response_mime_type="application/json",
                ),
            )

            return json.loads(response.text)

        except Exception as e:
            log.error("Game Brain nudge generation error: %s", e)
            return None

    # -- Context restoration (for reconnects) --

    async def get_restoration_context(self) -> str:
        """Get full context summary for restoring a reconnected session."""
        if not self._history:
            return "Game just started. No events yet."

        game_state = self._game_state_fn() if self._game_state_fn else {}
        full_history = [e.to_dict() for e in self._history[-50:]]

        prompt = CONTEXT_RESTORE_PROMPT.format(
            full_history=json.dumps(full_history, indent=2),
            game_state=json.dumps(game_state, indent=2),
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=BRAIN_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=BRAIN_SYSTEM_PROMPT,
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )

            result = json.loads(response.text)
            return result.get("restoration_prompt", "Session restored. Continue the game.")

        except Exception as e:
            log.error("Game Brain context restore error: %s", e)
            return f"Session restored. Current vibes: {game_state.get('vibes', 0)}, streak: {game_state.get('streak', 0)}."

    # -- Convenience: current context for nudger --

    def get_context_summary(self) -> str:
        """Get a lightweight context summary for the nudger (no API call)."""
        parts = [self._history_summary]

        # Recent events
        recent = self._history[-5:]
        if recent:
            event_strs = []
            for e in recent:
                if e.event_type == "score":
                    event_strs.append(f"+{e.data['points']} ({e.data['action']})")
                elif e.event_type == "penalty":
                    event_strs.append(f"-{e.data['points']} ({e.data['action']})")
                elif e.event_type == "player_speech":
                    event_strs.append("player spoke")
            if event_strs:
                parts.append("Recent: " + ", ".join(event_strs))

        return " | ".join(parts)

    # -- Background sync loop --

    async def _sync_loop(self):
        """Periodically analyze pending observations and update context."""
        await asyncio.sleep(BRAIN_UPDATE_INTERVAL)
        try:
            while self._running:
                if self._pending_observations:
                    await self.analyze_and_score()
                await asyncio.sleep(BRAIN_UPDATE_INTERVAL)
        except asyncio.CancelledError:
            pass
