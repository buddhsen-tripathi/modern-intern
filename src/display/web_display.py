"""Web display service — sends game state + audio over WebSocket."""

import json
import logging
import struct

from aiohttp import web

from src.config import TAG_MUSIC_AUDIO, TAG_NARRATION_AUDIO
from src.display.base import DisplayService

log = logging.getLogger(__name__)


class WebDisplayService(DisplayService):
    def __init__(self):
        self._ws = None

    def set_websocket(self, ws: web.WebSocketResponse):
        self._ws = ws

    def clear_websocket(self):
        self._ws = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def send_state(self, state: dict):
        await self._send_json({"type": "state", "data": state})

    async def send_event(self, event: dict):
        await self._send_json({"type": "event", "data": event})

    async def send_narration_text(self, text: str):
        await self._send_json({"type": "narration", "text": text})

    async def send_narration_audio(self, audio_bytes: bytes):
        await self._send_binary(TAG_NARRATION_AUDIO, audio_bytes)

    async def send_music_audio(self, audio_bytes: bytes):
        await self._send_binary(TAG_MUSIC_AUDIO, audio_bytes)

    async def _send_json(self, data: dict):
        if not self.connected:
            return
        try:
            await self._ws.send_str(json.dumps(data))
        except Exception as e:
            log.error(f"WS send JSON error: {e}")

    async def _send_binary(self, tag: int, data: bytes):
        if not self.connected:
            return
        try:
            await self._ws.send_bytes(struct.pack("B", tag) + data)
        except Exception as e:
            log.error(f"WS send binary error: {e}")
