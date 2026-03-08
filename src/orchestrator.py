"""Orchestrator: central brain that routes gestures and voice to agents.

Gestures = triggers (what to do)
Audio/voice = content (what to do it with)

Flow: gesture arms an action → Silas prompts user → user speaks → action executes.
"""

import logging
import os
import time

from src.agents.calendar_agent import CalendarAgent
from src.agents.email_agent import EmailAgent
from src.agents.meeting_agent import MeetingAgent
from src.agents.note_agent import NoteAgent
from src.config import GESTURE_COOLDOWN_SEC
from src.display.web_display import WebDisplayService
from src.services.gemini_service import GeminiService

log = logging.getLogger(__name__)

# Gesture → action type mapping
GESTURE_ACTION_MAP = {
    "open_palm": "note",
    "peace_sign": "draft_email",
    "point_up": "calendar_event",
    "wave": "meeting_minutes",
    "ok_sign": "send_email",
    "thumbs_up": "confirm",
}

# Prompts Silas speaks to solicit voice input after a gesture
GESTURE_PROMPTS = {
    "note": "Ready to take a note. What should I write down?",
    "draft_email": "Drafting an email. Who's it for and what should it say?",
    "calendar_event": "Creating a calendar event. What's the event and when?",
    "send_email": None,  # immediate action, no voice input needed
    "confirm": None,  # immediate action
}


class Orchestrator:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")

        self.display = WebDisplayService()
        self.gemini = GeminiService(api_key)
        self._started = False

        # Agents
        self._note_agent = NoteAgent()
        self._meeting_agent = MeetingAgent(api_key)
        self._email_agent = EmailAgent()
        self._calendar_agent = CalendarAgent()

        # Agent routing table
        self._agents = {
            "note": self._note_agent,
            "meeting_minutes": self._meeting_agent,
            "draft_email": self._email_agent,
            "send_email": self._email_agent,
            "read_email": self._email_agent,
            "calendar_event": self._calendar_agent,
        }

        # Pending action: gesture arms it, voice completes it
        self._pending_action: str | None = None
        self._pending_since: float = 0.0
        self._pending_timeout = 30.0  # seconds to wait for voice input

        # Gesture cooldown tracking
        self._last_gesture_time: float = 0.0

        # Recent observations for agent context
        self._observations: list[str] = []
        self._max_observations = 20

        # Wire Gemini callbacks
        self.gemini.set_callbacks(
            on_audio=self._on_narration_audio,
            on_narration=self._on_narration_text,
            on_gesture=self._on_gesture,
            on_action=self._on_action,
            on_vad_state=self._on_vad_state,
        )

    async def start_session(self):
        """Connect to Gemini and start watching — single step, no intro."""
        if self._started:
            return
        self._started = True
        log.info("Starting session...")
        await self.gemini.start_session()

    async def stop_session(self):
        if not self._started and not self.gemini.connected:
            return
        self._started = False
        self._pending_action = None
        log.info("Stopping session...")
        await self.gemini.stop()

    async def handle_video_frame(self, jpeg_bytes: bytes):
        await self.gemini.send_video_frame(jpeg_bytes)

    async def handle_mic_audio(self, pcm_data: bytes):
        await self.gemini.send_mic_audio(pcm_data)

    # -- Internal callbacks --

    async def _on_narration_audio(self, audio_bytes: bytes):
        await self.display.send_narration_audio(audio_bytes)

    async def _on_narration_text(self, text: str):
        await self.display.send_narration_text(text)
        # Feed to meeting agent if recording
        self._meeting_agent.add_entry(text)
        # Track observations for agent context
        self._observations.append(text)
        if len(self._observations) > self._max_observations:
            self._observations.pop(0)

    async def _on_gesture(self, gesture: str):
        now = time.monotonic()
        if now - self._last_gesture_time < GESTURE_COOLDOWN_SEC:
            log.info("Gesture %s ignored (cooldown)", gesture)
            return
        self._last_gesture_time = now

        action_type = GESTURE_ACTION_MAP.get(gesture)
        if not action_type:
            log.info("Unknown gesture: %s", gesture)
            return

        log.info("Gesture detected: %s → %s", gesture, action_type)
        await self.display.send_event({
            "type": "gesture",
            "gesture": gesture,
            "action": action_type,
        })

        # Meeting minutes: toggle immediately (no voice input needed)
        if action_type == "meeting_minutes":
            cmd = "stop" if self._meeting_agent.recording else "start"
            await self._execute_action("meeting_minutes", {"command": cmd})
            return

        # Send/confirm: execute immediately
        if action_type in ("send_email", "confirm"):
            await self._execute_action(action_type, {})
            return

        # For note, email, calendar: arm the action and wait for voice
        prompt = GESTURE_PROMPTS.get(action_type)
        self._pending_action = action_type
        self._pending_since = now
        log.info("Action armed: %s — waiting for voice input", action_type)

        await self.display.send_event({
            "type": "action_armed",
            "action": action_type,
            "prompt": prompt,
        })

        # Tell Gemini to prompt the user for input
        if prompt:
            await self.gemini.send_prompt(prompt)

    async def _on_action(self, action_type: str, params: dict):
        """Called when Gemini emits an <<ACTION>> tag (from voice command or
        after a gesture+voice sequence)."""

        # If there's a pending gesture-armed action, the voice input fills it
        if self._pending_action:
            elapsed = time.monotonic() - self._pending_since
            if elapsed < self._pending_timeout:
                armed = self._pending_action
                self._pending_action = None
                log.info("Pending action %s fulfilled with voice params", armed)
                await self._execute_action(armed, params)
                return
            else:
                log.info("Pending action %s expired", self._pending_action)
                self._pending_action = None

        # Direct voice command (no gesture needed)
        await self._execute_action(action_type, params)

    async def _execute_action(self, action_type: str, params: dict):
        agent = self._agents.get(action_type)
        if not agent:
            # Handle confirm separately
            if action_type == "confirm":
                log.info("Confirm acknowledged")
                await self.display.send_event({
                    "type": "action_result",
                    "action": "confirm",
                    "status": "success",
                    "message": "Confirmed.",
                })
                return
            log.warning("No agent for action: %s", action_type)
            return

        # Build context for agent
        context = {
            "recent_observations": self._observations[-5:],
            "session_active": self._started,
        }

        # Email agent needs to know the sub-action
        if action_type in ("draft_email", "send_email", "read_email"):
            sub_map = {
                "draft_email": "draft",
                "send_email": "send",
                "read_email": "read",
            }
            context["sub_action"] = sub_map[action_type]

        log.info("Executing agent: %s (%s)", agent.name, action_type)
        result = await agent.execute(params, context)
        log.info("Agent result: %s", result.get("message", ""))

        await self.display.send_event({
            "type": "action_result",
            "action": action_type,
            "agent": agent.name,
            **result,
        })

    async def _on_vad_state(self, state: str):
        await self.display.send_vad_state(state)

        # If pending action timed out, clear it
        if self._pending_action:
            elapsed = time.monotonic() - self._pending_since
            if elapsed >= self._pending_timeout:
                log.info("Pending action %s timed out", self._pending_action)
                self._pending_action = None
                await self.display.send_event({
                    "type": "action_timeout",
                    "message": "Action cancelled — no voice input received.",
                })

    # -- Terminal command helpers --

    async def inject_narration(self, text: str):
        await self.gemini.inject_narration(text)

    def get_status(self) -> dict:
        return {
            "started": self._started,
            "pending_action": self._pending_action,
            "meeting_recording": self._meeting_agent.recording,
            "notes_count": len(self._note_agent.get_notes()),
            "events_count": len(self._calendar_agent.get_events()),
            "observations": len(self._observations),
        }
