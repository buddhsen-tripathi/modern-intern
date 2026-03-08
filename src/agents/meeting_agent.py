"""Meeting minutes agent — captures and summarizes conversations."""

import json
import logging
import time

from google import genai
from google.genai import types

from src.agents.base import BaseAgent
from src.config import BRAIN_MODEL

log = logging.getLogger(__name__)


class MeetingAgent(BaseAgent):
    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)
        self._recording = False
        self._transcript: list[dict] = []
        self._start_time: float = 0.0
        self._summaries: list[dict] = []

    @property
    def name(self) -> str:
        return "Meeting Minutes"

    @property
    def recording(self) -> bool:
        return self._recording

    async def execute(self, params: dict, context: dict) -> dict:
        command = params.get("command", "start")

        if command == "start":
            return self._start_recording()
        elif command == "stop":
            return await self._stop_recording()
        else:
            return {"status": "error", "message": f"Unknown command: {command}"}

    def _start_recording(self) -> dict:
        if self._recording:
            return {"status": "error", "message": "Already recording minutes."}
        self._recording = True
        self._transcript.clear()
        self._start_time = time.time()
        log.info("Meeting minutes recording started")
        return {"status": "success", "message": "Started taking meeting minutes."}

    async def _stop_recording(self) -> dict:
        if not self._recording:
            return {"status": "error", "message": "Not currently recording."}
        self._recording = False
        duration = time.time() - self._start_time

        if not self._transcript:
            return {"status": "success", "message": "Meeting ended. No content captured."}

        summary = await self._summarize()
        result = {
            "status": "success",
            "message": f"Meeting minutes ready ({len(self._transcript)} entries, {duration:.0f}s).",
            "summary": summary,
            "entry_count": len(self._transcript),
            "duration_seconds": round(duration),
        }
        self._summaries.append(result)
        return result

    def add_entry(self, text: str, speaker: str = "unknown"):
        """Called by orchestrator to feed speech during recording."""
        if not self._recording:
            return
        if not text.strip():
            return
        self._transcript.append({
            "text": text.strip(),
            "speaker": speaker,
            "timestamp": time.time() - self._start_time,
        })

    async def _summarize(self) -> str:
        transcript_text = "\n".join(
            f"[{e['timestamp']:.0f}s] {e['speaker'].upper()}: {e['text']}"
            for e in self._transcript
        )
        prompt = (
            "Summarize the following meeting transcript into structured minutes.\n"
            "Include: key discussion points, decisions made, action items.\n"
            "Ignore any meta-comments about the recording process.\n"
            "Format as clean bullet points. Be concise.\n\n"
            f"Transcript:\n{transcript_text}"
        )
        try:
            response = await self._client.aio.models.generate_content(
                model=BRAIN_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.3),
            )
            return response.text
        except Exception as e:
            log.error("Meeting summary error: %s", e)
            return f"Summary unavailable. Raw entries: {len(self._transcript)}"
