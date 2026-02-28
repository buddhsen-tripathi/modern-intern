"""Lyria RealTime music service."""

import asyncio
import logging

from google import genai
from google.genai import types

from src.config import LYRIA_BPM, LYRIA_GUIDANCE, LYRIA_MODEL, LYRIA_TEMPERATURE

log = logging.getLogger(__name__)

MOODS = {
    "idle": {
        "density": 0.2,
        "brightness": 0.3,
        "prompts": [
            types.WeightedPrompt(
                text="ambient lo-fi chill melancholy sparse piano", weight=1.0,
            ),
        ],
    },
    "approaching": {
        "density": 0.4,
        "brightness": 0.5,
        "prompts": [
            types.WeightedPrompt(
                text="hopeful building anticipation light acoustic guitar", weight=1.0,
            ),
        ],
    },
    "action_scored": {
        "density": 0.7,
        "brightness": 0.8,
        "prompts": [
            types.WeightedPrompt(
                text="triumphant bright celebration orchestral uplifting", weight=1.0,
            ),
        ],
    },
    "streak": {
        "density": 0.8,
        "brightness": 0.9,
        "prompts": [
            types.WeightedPrompt(
                text="energetic driving momentum upbeat electronic funk", weight=1.0,
            ),
        ],
    },
    "legendary": {
        "density": 1.0,
        "brightness": 1.0,
        "prompts": [
            types.WeightedPrompt(
                text="epic heroic powerful full orchestra electronic hybrid", weight=1.0,
            ),
        ],
    },
    "draining": {
        "density": 0.15,
        "brightness": 0.2,
        "prompts": [
            types.WeightedPrompt(
                text="somber lonely sparse desolate ambient dark", weight=1.0,
            ),
        ],
    },
    "final_minute": {
        "density": 0.9,
        "brightness": 0.7,
        "prompts": [
            types.WeightedPrompt(
                text="urgent tense racing against time dramatic percussion", weight=1.0,
            ),
        ],
    },
    "victory": {
        "density": 0.9,
        "brightness": 1.0,
        "prompts": [
            types.WeightedPrompt(
                text="victorious celebration triumphant fanfare bright joyful", weight=1.0,
            ),
        ],
    },
    "defeat": {
        "density": 0.3,
        "brightness": 0.3,
        "prompts": [
            types.WeightedPrompt(
                text="bittersweet reflective gentle piano fading", weight=1.0,
            ),
        ],
    },
}


class LyriaService:
    def __init__(self, api_key: str):
        self._client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1alpha"},
        )
        self._session = None
        self._ctx = None
        self._running = False
        self._current_mood = "idle"
        self._on_audio = None
        self._receive_task = None

    def set_callbacks(self, on_audio=None):
        self._on_audio = on_audio

    async def start(self):
        log.info("Connecting to Lyria RealTime...")
        self._ctx = self._client.aio.live.music.connect(model=LYRIA_MODEL)
        self._session = await self._ctx.__aenter__()
        self._running = True

        initial = MOODS["idle"]
        await self._session.set_weighted_prompts(prompts=initial["prompts"])
        await self._session.set_music_generation_config(
            config=types.LiveMusicGenerationConfig(
                bpm=LYRIA_BPM,
                density=initial["density"],
                brightness=initial["brightness"],
                guidance=LYRIA_GUIDANCE,
                temperature=LYRIA_TEMPERATURE,
            )
        )
        await self._session.play()
        log.info("Lyria started (idle mood, BPM=%d)", LYRIA_BPM)

        self._receive_task = asyncio.create_task(self._receive_loop())

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

    async def set_mood(self, mood_name: str):
        if mood_name not in MOODS or not self._session:
            return
        if mood_name == self._current_mood:
            return

        mood = MOODS[mood_name]
        self._current_mood = mood_name
        log.info(f"Music mood -> {mood_name}")

        try:
            await self._session.set_weighted_prompts(prompts=mood["prompts"])
            await self._session.set_music_generation_config(
                config=types.LiveMusicGenerationConfig(
                    density=mood["density"],
                    brightness=mood["brightness"],
                )
            )
        except Exception as e:
            log.error(f"Error setting mood: {e}")

    async def _receive_loop(self):
        try:
            while self._running:
                try:
                    async for msg in self._session.receive():
                        if not self._running:
                            break
                        if msg.server_content and msg.server_content.audio_chunks:
                            for chunk in msg.server_content.audio_chunks:
                                if self._on_audio:
                                    asyncio.create_task(
                                        self._on_audio(chunk.data)
                                    )
                except Exception as e:
                    if not self._running:
                        break
                    log.error(f"Lyria receive error: {e}")
                    await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
