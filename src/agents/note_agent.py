"""Note-taking agent — stores notes in memory."""

import logging
import time

from src.agents.base import BaseAgent

log = logging.getLogger(__name__)


class NoteAgent(BaseAgent):
    def __init__(self):
        self._notes: list[dict] = []

    @property
    def name(self) -> str:
        return "Notes"

    async def execute(self, params: dict, context: dict) -> dict:
        content = params.get("content", "").strip()
        if not content:
            return {"status": "error", "message": "No note content provided."}

        note = {
            "content": content,
            "timestamp": time.time(),
        }
        self._notes.append(note)
        log.info("Note saved: %s", content[:80])
        return {
            "status": "success",
            "message": f"Note saved: {content[:60]}",
            "total_notes": len(self._notes),
        }

    def get_notes(self) -> list[dict]:
        return list(self._notes)

    def clear(self):
        self._notes.clear()
