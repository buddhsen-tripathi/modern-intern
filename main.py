"""JOYBAIT — spread the love game server."""

import asyncio
import json
import logging
import sys

from aiohttp import web
from dotenv import load_dotenv

# Fix aiohttp tcp_keepalive crash on macOS (OSError: Invalid argument).
# Must patch on web_protocol since it imports the function by name directly.
import aiohttp.web_protocol as _wp

_orig_tcp_keepalive = _wp.tcp_keepalive


def _safe_tcp_keepalive(transport):
    try:
        _orig_tcp_keepalive(transport)
    except OSError:
        pass


_wp.tcp_keepalive = _safe_tcp_keepalive

from src.config import HOST, PORT
from src.server import create_app

load_dotenv()

log = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

HELP_TEXT = """\
  Commands:
    start                        — start the game
    stop                         — stop the game
    score <action> <pts> [desc]  — simulate a score event
    penalize <action> <pts>      — simulate a penalty
    music <mood>                 — change music mood
    say <text>                   — inject narration text
    status                       — print current game state
    help                         — show this message
"""


async def _stdin_reader(app: web.Application):
    """Read commands from stdin and dispatch to the orchestrator."""
    orch = app["orchestrator"]
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
    )

    while True:
        try:
            line_bytes = await reader.readline()
            if not line_bytes:
                break
            line = line_bytes.decode().strip()
            if not line:
                continue

            parts = line.split(maxsplit=1)
            cmd = parts[0].lower()
            rest = parts[1] if len(parts) > 1 else ""

            if cmd == "help":
                print(HELP_TEXT)

            elif cmd == "start":
                await orch.start_game()
                print("  Game started.")

            elif cmd == "stop":
                await orch.stop_game()
                print("  Game stopped.")

            elif cmd == "score":
                tokens = rest.split(maxsplit=2)
                if len(tokens) < 2:
                    print("  Usage: score <action> <points> [description]")
                    continue
                action = tokens[0]
                try:
                    pts = int(tokens[1])
                except ValueError:
                    print("  Points must be a number.")
                    continue
                desc = tokens[2] if len(tokens) > 2 else ""
                orch.inject_score(action, pts, desc)
                print(f"  Scored: {action} +{pts}")

            elif cmd == "penalize":
                tokens = rest.split(maxsplit=1)
                if len(tokens) < 2:
                    print("  Usage: penalize <action> <points>")
                    continue
                action = tokens[0]
                try:
                    pts = int(tokens[1])
                except ValueError:
                    print("  Points must be a number.")
                    continue
                orch.inject_penalize(action, pts)
                print(f"  Penalized: {action} -{pts}")

            elif cmd == "music":
                if not rest:
                    print("  Usage: music <mood>")
                    continue
                await orch.inject_music(rest.strip())
                print(f"  Music mood: {rest.strip()}")

            elif cmd == "say":
                if not rest:
                    print("  Usage: say <text>")
                    continue
                await orch.inject_narration(rest)
                print(f"  Injected narration.")

            elif cmd == "status":
                status = orch.get_status()
                print(f"  {json.dumps(status, indent=2)}")

            else:
                print(f"  Unknown command: {cmd}. Type 'help' for commands.")

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("stdin command error: %s", e)


async def _start_stdin_reader(app: web.Application):
    if not sys.stdin.isatty():
        log.info("Non-interactive mode — CLI commands disabled")
        return
    app["stdin_task"] = asyncio.create_task(_stdin_reader(app))


async def _stop_stdin_reader(app: web.Application):
    task = app.get("stdin_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    app = create_app()
    app.on_startup.append(_start_stdin_reader)
    app.on_cleanup.append(_stop_stdin_reader)
    print(f"\n  JOYBAIT — spread the love")
    print(f"  Server: http://{HOST}:{PORT}")
    print(f"  Open on phone: http://<your-ip>:{PORT}")
    print()
    print("  Routes:")
    print("    /      — JOYBAIT")
    print()
    print("  Cloudflare: run 'cloudflared tunnel --url http://localhost:8080'")
    print("  Type 'help' for terminal commands.\n")
    web.run_app(app, host=HOST, port=PORT, print=None)
