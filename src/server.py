"""aiohttp app factory, routes, and WebSocket handler."""

import json
import logging
import pathlib

from aiohttp import WSMsgType, web

from src.config import TAG_CAMERA, TAG_MIC_AUDIO
from src.orchestrator import Orchestrator

log = logging.getLogger(__name__)

ROOT = pathlib.Path(__file__).resolve().parent.parent


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
                    elif cmd == "skip_task":
                        orch.skip_task()
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


async def index_handler(request: web.Request):
    return web.FileResponse(ROOT / "templates" / "index.html")


def create_app() -> web.Application:
    app = web.Application()
    app["orchestrator"] = Orchestrator()

    app.router.add_get("/", index_handler)
    app.router.add_get("/ws/game", ws_game_handler)
    app.router.add_static("/static/", ROOT / "static")

    return app
