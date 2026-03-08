"""Calendar agent — create events.

Currently a stub that stores events locally.
TODO: Integrate with Google Calendar API via OAuth2.
"""

import logging
import time

from src.agents.base import BaseAgent

log = logging.getLogger(__name__)


class CalendarAgent(BaseAgent):
    def __init__(self):
        self._events: list[dict] = []

    @property
    def name(self) -> str:
        return "Calendar"

    async def execute(self, params: dict, context: dict) -> dict:
        title = params.get("title", "Untitled Event")
        start = params.get("start", "")
        duration = params.get("duration_minutes", 30)
        description = params.get("description", "")

        event = {
            "title": title,
            "start": start,
            "duration_minutes": duration,
            "description": description,
            "created_at": time.time(),
        }
        self._events.append(event)

        # TODO: actual Google Calendar API create
        log.info("Calendar event created (stub): %s at %s", title, start or "TBD")
        return {
            "status": "success",
            "message": f"Event created: \"{title}\" {f'at {start}' if start else '(time TBD)'}",
            "event": event,
        }

    def get_events(self) -> list[dict]:
        return list(self._events)
