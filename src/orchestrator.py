"""Orchestrator: central brain that routes voice commands to agents.

Voice-only mode: user speaks commands, Silas responds and executes actions.
"""

import logging
import os

from src.agents.calendar_agent import CalendarAgent
from src.agents.email_agent import EmailAgent
from src.agents.meeting_agent import MeetingAgent
from src.agents.document_agent import DocumentAgent
from src.agents.note_agent import NoteAgent
from src.agents.search_agent import SearchAgent
from src.display.web_display import WebDisplayService
from src.services.gemini_service import GeminiService
from src.services.discord_service import DiscordService

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set in environment")

        self.display = WebDisplayService()
        self.gemini = GeminiService(api_key)
        self.discord = DiscordService()
        self._started = False

        # Agents
        self._note_agent = NoteAgent()
        self._meeting_agent = MeetingAgent(api_key)
        self._email_agent = EmailAgent()
        self._calendar_agent = CalendarAgent()
        self._search_agent = SearchAgent(api_key)
        self._document_agent = DocumentAgent(api_key)

        # Agent routing table
        self._agents = {
            "note": self._note_agent,
            "note_start": self._note_agent,
            "note_stop": self._note_agent,
            "meeting_minutes": self._meeting_agent,
            "meeting_minutes_start": self._meeting_agent,
            "meeting_minutes_stop": self._meeting_agent,
            "draft_email": self._email_agent,
            "send_email": self._email_agent,
            "read_email": self._email_agent,
            "calendar_event": self._calendar_agent,
            "search": self._search_agent,
            "create_document": self._document_agent,
        }

        # Note recording state
        self._note_recording = False
        self._note_buffer: list[str] = []
        self._skip_next_narration = False

        # Recent observations for agent context
        self._observations: list[str] = []
        self._max_observations = 20

        # Wire Gemini callbacks
        self.gemini.set_callbacks(
            on_audio=self._on_narration_audio,
            on_narration=self._on_narration_text,
            on_action=self._on_action,
            on_vad_state=self._on_vad_state,
            on_user_speech=self._on_user_speech,
        )

    async def start_session(self):
        """Connect to Gemini and start listening."""
        if self._started:
            return
        self._started = True
        log.info("Starting session...")
        await self.gemini.start_session()

    async def stop_session(self):
        if not self._started and not self.gemini.connected:
            return
        self._started = False
        log.info("Stopping session...")
        await self.gemini.stop()
        await self.discord.close()

    async def handle_mic_audio(self, pcm_data: bytes):
        await self.gemini.send_mic_audio(pcm_data)

    async def handle_text_input(self, text: str):
        """Handle typed text from the UI — fed to Gemini as user input."""
        log.info("Text input: %s", text[:200])
        # Feed to meeting agent if recording
        self._meeting_agent.add_entry(text, speaker="user")
        # Buffer for note if recording
        if self._note_recording and text.strip():
            self._note_buffer.append(text.strip())
        # Send to Gemini as if user spoke it
        await self.gemini.send_prompt(f"The user typed: {text}")

    # -- Internal callbacks --

    async def _on_narration_audio(self, audio_bytes: bytes):
        await self.display.send_narration_audio(audio_bytes)

    async def _on_narration_text(self, text: str):
        await self.display.send_narration_text(text)
        # Skip Gemini's confirmation after note_start so it's not captured
        if self._skip_next_narration:
            self._skip_next_narration = False
            return
        # Feed assistant speech to meeting agent (skip meta-comments)
        if not self._is_meta_comment(text):
            self._meeting_agent.add_entry(text, speaker="assistant")
        # Buffer narration while note is recording
        if self._note_recording and text.strip():
            self._note_buffer.append(text.strip())
        # Track observations for agent context
        self._observations.append(text)
        if len(self._observations) > self._max_observations:
            self._observations.pop(0)

    async def _on_user_speech(self, text: str):
        """Called when user's speech is transcribed."""
        log.info("User said: %s", text[:200])
        # Feed user speech to meeting agent
        self._meeting_agent.add_entry(text, speaker="user")
        # Buffer user speech while note is recording
        if self._note_recording and text.strip():
            self._note_buffer.append(text.strip())

    @staticmethod
    def _is_meta_comment(text: str) -> bool:
        """Filter out Gemini's meta-comments about its own process."""
        lower = text.lower().strip()
        meta_phrases = (
            "started taking meeting",
            "i've started",
            "i will transcribe",
            "please continue",
            "i'm listening",
            "go ahead",
            "recording meeting",
            "taking minutes",
            "meeting minutes ready",
            "action:",
        )
        return any(p in lower for p in meta_phrases)

    async def _on_action(self, action_type: str, params: dict):
        """Called when Gemini announces an action via speech."""
        await self._execute_action(action_type, params)

    async def _execute_action(self, action_type: str, params: dict):
        # Handle note start/stop (continuous dictation)
        if action_type == "note_start":
            if self._note_recording:
                log.info("Note recording already active")
                return
            # Skip the next narration so Gemini's confirmation isn't captured as note content
            self._skip_next_narration = True
            self._note_recording = True
            self._note_buffer.clear()
            log.info(">>> NOTE RECORDING STARTED")
            await self.display.send_event({
                "type": "action_result",
                "action": "note_start",
                "agent": "Notes",
                "status": "success",
                "message": "Recording note... say 'note end' when done.",
            })
            return

        if action_type == "note_stop":
            if not self._note_recording:
                log.info("No note recording active")
                return
            self._note_recording = False
            content = " ".join(self._note_buffer).strip()
            self._note_buffer.clear()
            if content:
                log.info(">>> NOTE RECORDING STOPPED, saving %d chars", len(content))
                result = await self._note_agent.execute(
                    {"content": content},
                    {"recent_observations": self._observations[-5:], "session_active": self._started},
                )
                msg = result.get("message", "Note saved.")
                await self.display.send_event({
                    "type": "action_result",
                    "action": "note",
                    "agent": "Notes",
                    **result,
                })
                await self.discord.send_action_result("note", result)
                await self.gemini.send_prompt(msg)
            else:
                log.info(">>> NOTE RECORDING STOPPED, nothing captured")
                await self.display.send_event({
                    "type": "action_result",
                    "action": "note",
                    "agent": "Notes",
                    "status": "error",
                    "message": "No content captured.",
                })
                await self.gemini.send_prompt("Nothing to save.")
            return

        # Normalize meeting_minutes_start/stop
        if action_type == "meeting_minutes_start":
            action_type = "meeting_minutes"
            params = {"command": "start"}
        elif action_type == "meeting_minutes_stop":
            action_type = "meeting_minutes"
            params = {"command": "stop"}

        log.info(">>> EXECUTE: %s params=%s", action_type, params)
        agent = self._agents.get(action_type)
        if not agent:
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
        msg = result.get("message", "Done.")
        log.info("Agent result: %s", msg)

        # Validation errors — ask user for missing info, don't send to Discord
        if result.get("status") == "error" and result.get("error_type"):
            await self.display.send_event({
                "type": "action_result",
                "action": action_type,
                "agent": agent.name,
                **result,
            })
            await self.gemini.send_prompt(msg)
            return

        # Send result to display
        await self.display.send_event({
            "type": "action_result",
            "action": action_type,
            "agent": agent.name,
            **result,
        })

        # Send to Discord (only successful results)
        if result.get("status") == "success":
            await self.discord.send_action_result(action_type, result)

        # Have Silas speak the result aloud
        await self.gemini.send_prompt(msg)

    async def _on_vad_state(self, state: str):
        await self.display.send_vad_state(state)

    # -- Terminal command helpers --

    async def inject_narration(self, text: str):
        await self.gemini.send_prompt(text)

    def get_status(self) -> dict:
        return {
            "started": self._started,
            "note_recording": self._note_recording,
            "meeting_recording": self._meeting_agent.recording,
            "notes_count": len(self._note_agent.get_notes()),
            "events_count": len(self._calendar_agent.get_events()),
            "observations": len(self._observations),
            "discord": self.discord.enabled,
        }
