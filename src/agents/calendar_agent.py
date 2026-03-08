"""Calendar agent — create events stored locally, confirmed via Discord.

Parses event details from voice commands. No external API needed.
"""

import logging
import time
from datetime import datetime, timedelta

from src.agents.base import BaseAgent

log = logging.getLogger(__name__)


class CalendarAgent(BaseAgent):
    def __init__(self):
        self._events: list[dict] = []

    @property
    def name(self) -> str:
        return "Calendar"

    async def execute(self, params: dict, context: dict) -> dict:
        title = params.get("title", "").strip()
        date = params.get("date", "").strip()
        time_str = params.get("time", "").strip()
        duration = params.get("duration", "").strip()
        participants = params.get("participants", "").strip()

        if not title:
            return {
                "status": "error",
                "error_type": "missing_title",
                "message": "What's the event about?",
            }

        if not date and not time_str:
            return {
                "status": "error",
                "error_type": "missing_datetime",
                "message": f"When is \"{title}\"? I need a date and time.",
            }

        event = {
            "title": title,
            "date": date or "TBD",
            "time": time_str or "TBD",
            "duration": duration or "30 min",
            "participants": participants,
            "created_at": time.time(),
        }
        self._events.append(event)

        log.info("Calendar event created: %s on %s at %s", title, date, time_str)

        # Build confirmation message
        details = [f"Event: {title}"]
        if date:
            details.append(f"Date: {date}")
        if time_str:
            details.append(f"Time: {time_str}")
        if duration:
            details.append(f"Duration: {duration}")
        if participants:
            details.append(f"With: {participants}")

        confirmation = " | ".join(details)

        return {
            "status": "success",
            "message": confirmation,
            "event": event,
        }

    def get_events(self) -> list[dict]:
        return list(self._events)
