"""Game state management for Kindness Speedrun."""

import asyncio
import time

from src.config import GAME_DURATION, RANK_THRESHOLDS


class GameStateManager:
    def __init__(self):
        self.essence = 0
        self.streak = 0
        self.timer_remaining = GAME_DURATION
        self.running = False
        self.game_over = False
        self._timer_task = None

        # Callbacks
        self._on_state_change = None
        self._on_event = None

    def set_callbacks(self, on_state_change=None, on_event=None):
        self._on_state_change = on_state_change
        self._on_event = on_event

    @property
    def multiplier(self) -> int:
        if self.streak >= 5:
            return 3
        if self.streak >= 3:
            return 2
        return 1

    @property
    def rank(self) -> str:
        for name, threshold in RANK_THRESHOLDS:
            if self.essence >= threshold:
                return name
        return "Bronze"

    def to_dict(self) -> dict:
        return {
            "essence": self.essence,
            "streak": self.streak,
            "multiplier": self.multiplier,
            "timer": round(self.timer_remaining, 1),
            "rank": self.rank,
            "running": self.running,
            "gameOver": self.game_over,
        }

    def start(self):
        self.essence = 0
        self.streak = 0
        self.timer_remaining = GAME_DURATION
        self.running = True
        self.game_over = False
        self._timer_task = asyncio.create_task(self._run_timer())
        self._notify_state()

    async def _run_timer(self):
        start = time.monotonic()
        try:
            while self.running and self.timer_remaining > 0:
                await asyncio.sleep(1.0)
                elapsed = time.monotonic() - start
                self.timer_remaining = max(0, GAME_DURATION - elapsed)
                self._notify_state()
                if self.timer_remaining <= 0:
                    self.running = False
                    self.game_over = True
                    self._notify_state()
        except asyncio.CancelledError:
            pass

    def score(self, action_type: str, points: int, description: str = ""):
        if not self.running:
            return
        self.streak += 1
        actual = points * self.multiplier
        self.essence += actual
        if self._on_event:
            asyncio.create_task(self._on_event({
                "type": "score",
                "action": action_type,
                "points": actual,
                "multiplier": self.multiplier,
                "description": description,
            }))
        self._notify_state()

    def penalize(self, action_type: str, points: int):
        if not self.running:
            return
        self.essence = max(0, self.essence - points)
        self.streak = 0
        if self._on_event:
            asyncio.create_task(self._on_event({
                "type": "penalize",
                "action": action_type,
                "points": points,
            }))
        self._notify_state()

    def stop(self):
        self.running = False
        self.game_over = True
        if self._timer_task:
            self._timer_task.cancel()
        self._notify_state()

    def _notify_state(self):
        if self._on_state_change:
            asyncio.create_task(self._on_state_change(self.to_dict()))
