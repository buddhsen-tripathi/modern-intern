"""Orchestrator: wires all services and routes events between them."""

import logging
import os

from src.display.web_display import WebDisplayService
from src.services.game_brain import GameBrainService
from src.services.game_state import GameStateManager
from src.services.gemini_service import GeminiService
from src.services.lyria_service import LyriaService

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")

        self.display = WebDisplayService()
        self.game = GameStateManager()
        self.gemini = GeminiService(api_key)
        self.lyria = LyriaService(api_key)
        self.brain = GameBrainService(api_key)
        self._started = False
        self._final_minute_triggered = False

        # Wire Gemini Live API callbacks
        # Audio + narration text still come from Live API (latency-sensitive)
        # Scoring tags from Live API are kept as a fallback; brain handles primary scoring
        self.gemini.set_callbacks(
            on_audio=self._on_narration_audio,
            on_narration=self._on_narration_text,
            on_score=self._on_score,
            on_penalize=self._on_penalize,
            on_music=self._on_music,
            on_task=self._on_task,
            on_vad_state=self._on_vad_state,
        )
        self.gemini.set_game_state_fn(self.game.to_dict)

        # Wire Game Brain callbacks (parallel scoring pipeline)
        self.brain.set_callbacks(
            on_score=self._on_brain_score,
            on_penalize=self._on_brain_penalize,
            on_music=self._on_music,
            on_task=self._on_task,
        )
        self.brain.set_game_state_fn(self.game.to_dict)

        # Give Gemini access to brain for contextual nudges and reconnect
        self.gemini.set_brain(self.brain)

        # Wire GameState callbacks
        self.game.set_callbacks(
            on_state_change=self._on_state_change,
            on_event=self._on_event,
        )

        # Wire Lyria callbacks
        self.lyria.set_callbacks(
            on_audio=self._on_music_audio,
        )

    async def play_intro(self):
        """Connect to Gemini and play intro narration only."""
        if self.gemini.connected:
            return
        log.info("Playing intro narration...")
        await self.gemini.connect_and_intro()

    async def start_game(self):
        if self._started:
            return
        self._started = True
        self._final_minute_triggered = False
        log.info("Starting game...")
        self.brain.start()
        await self.gemini.begin_game()
        await self.lyria.start()
        self.game.start()

    async def stop_game(self):
        if not self._started and not self.gemini.connected:
            return
        self._started = False
        log.info("Stopping game...")
        self.game.stop()
        await self.gemini.stop()
        await self.lyria.stop()
        await self.brain.stop()

    async def handle_video_frame(self, jpeg_bytes: bytes):
        await self.gemini.send_video_frame(jpeg_bytes)

    async def handle_mic_audio(self, pcm_data: bytes):
        await self.gemini.send_mic_audio(pcm_data)

    # -- Internal callbacks --

    async def _on_narration_audio(self, audio_bytes: bytes):
        await self.display.send_narration_audio(audio_bytes)

    async def _on_narration_text(self, text: str):
        await self.display.send_narration_text(text)
        # Feed narration text to brain as an observation
        self.brain.record_observation(text)

    async def _on_score(self, action: str, points: int, description: str):
        """Score from Live API tags (fallback path)."""
        self.game.score(action, points, description)
        self.brain.record_score(action, points, description)

    async def _on_brain_score(self, action: str, points: int, description: str):
        """Score from Game Brain analysis (primary path)."""
        self.game.score(action, points, description)

    async def _on_penalize(self, action: str, points: int):
        """Penalty from Live API tags (fallback path)."""
        self.game.penalize(action, points)
        self.brain.record_penalty(action, points)

    async def _on_brain_penalize(self, action: str, points: int):
        """Penalty from Game Brain analysis (primary path)."""
        self.game.penalize(action, points)

    async def _on_music(self, mood: str):
        await self.lyria.set_mood(mood)
        self.brain.record_mood_change(mood)

    def skip_task(self):
        self.game.skip_task()

    async def _on_task(self, text: str, bonus: int):
        self.game.set_task(text, bonus)
        self.brain.record_task(text, bonus)
        await self.display.send_event({"type": "task", "text": text, "bonus": bonus})

    async def _on_state_change(self, state: dict):
        await self.display.send_state(state)
        # Auto-trigger final_minute music and game over mood
        timer = state.get("timer", 999)
        if timer <= 60 and not self._final_minute_triggered:
            self._final_minute_triggered = True
            await self.lyria.set_mood("final_minute")
        if state.get("gameOver"):
            mood = "victory" if state.get("vibes", 0) >= 400 else "defeat"
            await self.lyria.set_mood(mood)

    async def _on_event(self, event: dict):
        await self.display.send_event(event)

    async def _on_vad_state(self, state: str):
        await self.display.send_vad_state(state)
        if state == "LISTENING":
            self.brain.record_player_speech()

    async def _on_music_audio(self, audio_bytes: bytes):
        await self.display.send_music_audio(audio_bytes)

    # -- Terminal command helpers --

    async def inject_narration(self, text: str):
        await self.gemini.inject_narration(text)

    def inject_score(self, action: str, points: int, desc: str = ""):
        self.game.score(action, points, desc)
        self.brain.record_score(action, points, desc)
        log.info("Injected SCORE: %s +%d -- %s", action, points, desc)

    def inject_penalize(self, action: str, points: int):
        self.game.penalize(action, points)
        self.brain.record_penalty(action, points)
        log.info("Injected PENALIZE: %s -%d", action, points)

    async def inject_music(self, mood: str):
        await self.lyria.set_mood(mood)
        self.brain.record_mood_change(mood)
        log.info("Injected MUSIC: %s", mood)

    def get_status(self) -> dict:
        return {
            "started": self._started,
            "game": self.game.to_dict(),
            "brain_context": self.brain.get_context_summary(),
        }
