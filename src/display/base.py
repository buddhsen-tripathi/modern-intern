"""Abstract display service interface."""

from abc import ABC, abstractmethod


class DisplayService(ABC):
    @abstractmethod
    async def send_state(self, state: dict):
        """Send assistant state update."""

    @abstractmethod
    async def send_event(self, event: dict):
        """Send assistant event (action triggered, completed, etc)."""

    @abstractmethod
    async def send_narration_text(self, text: str):
        """Send narration subtitle text."""

    @abstractmethod
    async def send_narration_audio(self, audio_bytes: bytes):
        """Send narration audio (24kHz mono PCM)."""

    @abstractmethod
    async def send_vad_state(self, state: str):
        """Send VAD state update (LISTENING, IDLE, PENDING)."""
