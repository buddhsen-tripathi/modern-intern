"""Abstract display service interface."""

from abc import ABC, abstractmethod


class DisplayService(ABC):
    @abstractmethod
    async def send_state(self, state: dict):
        """Send game state update."""

    @abstractmethod
    async def send_event(self, event: dict):
        """Send game event (score/penalize toast)."""

    @abstractmethod
    async def send_narration_text(self, text: str):
        """Send narration subtitle text."""

    @abstractmethod
    async def send_narration_audio(self, audio_bytes: bytes):
        """Send narration audio (24kHz mono PCM)."""

    @abstractmethod
    async def send_music_audio(self, audio_bytes: bytes):
        """Send music audio (48kHz stereo PCM)."""

    @abstractmethod
    async def send_vad_state(self, state: str):
        """Send VAD state update (LISTENING, IDLE, PENDING)."""
