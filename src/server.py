"""aiohttp app factory, routes, and WebSocket handler."""

import json
import logging
import os
import pathlib
import struct

from aiohttp import WSMsgType, web

from src.config import TAG_CAMERA, TAG_MIC_AUDIO, TAG_NARRATION_AUDIO
from src.orchestrator import Orchestrator
from src.services.gemini_service import GeminiService

log = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Chat system prompt (conversational, no game mechanics)
CHAT_SYSTEM_PROMPT = """\
You are a helpful, conversational AI assistant with access to a live camera feed.
You can see what the user's camera is pointing at in real time.

BEHAVIOR:
- Answer questions about what you see naturally and concisely
- When the user asks "what do you see?" describe the scene briefly
- Keep responses SHORT (1-3 sentences) so the conversation feels natural
- Be casual and friendly, like a knowledgeable friend looking over their shoulder
- If you're not sure what something is, say so honestly
- You can reference things you saw earlier in the conversation
"""


async def ws_game_handler(request: web.Request):
    ws = web.WebSocketResponse(max_msg_size=4 * 1024 * 1024)  # 4 MB for JPEG frames
    await ws.prepare(request)

    orch: Orchestrator = request.app["orchestrator"]
    orch.display.set_websocket(ws)
    log.info("Phone connected via WebSocket")

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    cmd = data.get("type")
                    if cmd == "intro":
                        await orch.play_intro()
                    elif cmd == "start":
                        await orch.start_game()
                    elif cmd == "stop":
                        await orch.stop_game()
                except json.JSONDecodeError:
                    log.warning("Bad JSON from client")

            elif msg.type == WSMsgType.BINARY:
                if len(msg.data) < 2:
                    continue
                tag = msg.data[0]
                payload = msg.data[1:]
                if tag == TAG_CAMERA:
                    await orch.handle_video_frame(payload)
                elif tag == TAG_MIC_AUDIO:
                    await orch.handle_mic_audio(payload)

            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        orch.display.clear_websocket()
        if orch._started or orch.gemini.connected:
            await orch.stop_game()
        log.info("Phone disconnected")

    return ws


async def ws_chat_handler(request: web.Request):
    """WebSocket handler for Gemini voice+vision chat (no game mechanics)."""
    ws = web.WebSocketResponse(max_msg_size=4 * 1024 * 1024)
    await ws.prepare(request)
    log.info("Chat client connected via WebSocket")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        await ws.send_str(json.dumps({"type": "error", "text": "GEMINI_API_KEY not set"}))
        return ws

    gemini = GeminiService(api_key, system_prompt=CHAT_SYSTEM_PROMPT)

    # Wire callbacks to send audio/text back via this WS
    async def on_audio(audio_bytes):
        if not ws.closed:
            try:
                await ws.send_bytes(struct.pack("B", TAG_NARRATION_AUDIO) + audio_bytes)
            except Exception:
                pass

    async def on_narration(text):
        if not ws.closed:
            try:
                await ws.send_str(json.dumps({"type": "narration", "text": text}))
            except Exception:
                pass

    gemini.set_callbacks(on_audio=on_audio, on_narration=on_narration)

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "start":
                        if not gemini.connected:
                            await gemini.connect_and_intro()
                except json.JSONDecodeError:
                    pass

            elif msg.type == WSMsgType.BINARY:
                if len(msg.data) < 2:
                    continue
                tag = msg.data[0]
                payload = msg.data[1:]
                if tag == TAG_CAMERA:
                    await gemini.send_video_frame(payload)
                elif tag == TAG_MIC_AUDIO:
                    await gemini.send_mic_audio(payload)

            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        await gemini.stop()
        log.info("Chat client disconnected")

    return ws


async def index_handler(request: web.Request):
    return web.FileResponse(ROOT / "templates" / "index.html")


async def chat_handler(request: web.Request):
    return web.FileResponse(ROOT / "templates" / "chat.html")


def create_app() -> web.Application:
    app = web.Application()
    app["orchestrator"] = Orchestrator()

    app.router.add_get("/", index_handler)
    app.router.add_get("/chat", chat_handler)
    app.router.add_get("/ws/game", ws_game_handler)
    app.router.add_get("/ws/chat", ws_chat_handler)
    app.router.add_static("/static/", ROOT / "static")

    return app
