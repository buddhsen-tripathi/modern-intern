"""Game state management for JOYBAIT."""

import asyncio
import time

from src.config import GAME_DURATION, IDLE_PENALTY_POINTS, IDLE_PENALTY_TIMEOUT, RANK_THRESHOLDS


class GameStateManager:
    def __init__(self):
        self.vibes = 0
        self.streak = 0
        self.timer_remaining = GAME_DURATION
        self.running = False
        self.game_over = False
        self._timer_task = None

        # Task state
        self.active_task = None  # dict: {text, bonus} or None
        self.tasks_completed = 0

        # Idle penalty tracking
        self.last_score_time = 0.0

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
            if self.vibes >= threshold:
                return name
        return "Basic"

    def to_dict(self) -> dict:
        d = {
            "vibes": self.vibes,
            "streak": self.streak,
            "multiplier": self.multiplier,
            "timer": round(self.timer_remaining, 1),
            "rank": self.rank,
            "running": self.running,
            "gameOver": self.game_over,
            "tasksCompleted": self.tasks_completed,
        }
        if self.active_task:
            d["activeTask"] = self.active_task
        return d

    def start(self):
        self.vibes = 0
        self.streak = 0
        self.timer_remaining = GAME_DURATION
        self.running = True
        self.game_over = False
        self.active_task = None
        self.tasks_completed = 0
        self.last_score_time = time.monotonic()
        self._timer_task = asyncio.create_task(self._run_timer())
        self._notify_state()

    async def _run_timer(self):
        start = time.monotonic()
        try:
            while self.running and self.timer_remaining > 0:
                await asyncio.sleep(1.0)
                now = time.monotonic()
                elapsed = now - start
                self.timer_remaining = max(0, GAME_DURATION - elapsed)
                # Deterministic idle penalty
                if now - self.last_score_time >= IDLE_PENALTY_TIMEOUT:
                    self._apply_idle_penalty()
                    self.last_score_time = now
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
        self.vibes += actual
        self.last_score_time = time.monotonic()
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
        self.vibes = max(0, self.vibes - points)
        self.streak = 0
        if self._on_event:
            asyncio.create_task(self._on_event({
                "type": "penalize",
                "action": action_type,
                "points": points,
            }))
        self._notify_state()

    def set_task(self, text: str, bonus: int):
        self.active_task = {"text": text, "bonus": bonus}
        self._notify_state()

    def skip_task(self):
        if not self.active_task or not self.running:
            return
        self.vibes = max(0, self.vibes - 2)
        self.active_task = None
        if self._on_event:
            asyncio.create_task(self._on_event({
                "type": "skip_task",
                "points": 2,
            }))
        self._notify_state()

    def _apply_idle_penalty(self):
        if not self.running:
            return
        self.vibes = max(0, self.vibes - IDLE_PENALTY_POINTS)
        self.streak = 0
        if self._on_event:
            asyncio.create_task(self._on_event({
                "type": "penalize",
                "action": "idle",
                "points": IDLE_PENALTY_POINTS,
            }))

    def complete_task(self):
        if not self.active_task or not self.running:
            return
        bonus = self.active_task["bonus"]
        self.vibes += bonus
        self.tasks_completed += 1
        self.active_task = None
        if self._on_event:
            asyncio.create_task(self._on_event({
                "type": "task",
                "points": bonus,
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
