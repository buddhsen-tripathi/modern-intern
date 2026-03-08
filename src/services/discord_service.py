"""Discord notification service — sends action results to Discord via the Chat SDK sidecar.

POSTs to the Node.js Discord bot running on DISCORD_NOTIFY_PORT (default 3100).
"""

import logging
import os

import aiohttp

log = logging.getLogger(__name__)


class DiscordService:
    def __init__(self):
        self._port = int(os.getenv("DISCORD_NOTIFY_PORT", "3100"))
        self._base_url = f"http://localhost:{self._port}"
        self._session: aiohttp.ClientSession | None = None
        self._channel_id = os.getenv("DISCORD_CHANNEL_ID", "")

        if not self._channel_id:
            log.warning("Discord not configured — set DISCORD_CHANNEL_ID")

    @property
    def enabled(self) -> bool:
        return bool(self._channel_id)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def send_message(self, text: str) -> bool:
        """Send a markdown message to the Discord channel via sidecar."""
        if not self.enabled:
            return False

        try:
            session = await self._get_session()
            async with session.post(
                f"{self._base_url}/notify",
                json={"message": text},
            ) as resp:
                if resp.status == 200:
                    log.info("Discord message sent")
                    return True
                else:
                    body = await resp.text()
                    log.error("Discord sidecar error %d: %s", resp.status, body[:200])
                    return False
        except Exception as e:
            log.error("Discord send failed: %s", e)
            return False

    async def send_action_result(self, action: str, result: dict):
        """Format and send an action result to Discord."""
        formatter = ACTION_FORMATTERS.get(action, _format_generic)
        text = formatter(action, result)
        if text:
            await self.send_message(text)


# -- Formatters (markdown for Discord) --

def _format_note(action: str, result: dict) -> str:
    status = result.get("status", "")
    msg = result.get("message", "")
    total = result.get("total_notes", "")
    if status == "error":
        return ""
    return f"**Note Saved**\n{msg}\n*Total notes: {total}*"


def _format_note_start(action: str, result: dict) -> str:
    if result.get("status") == "success":
        return "**Note Recording Started**\nListening..."
    return ""


def _format_meeting(action: str, result: dict) -> str:
    status = result.get("status", "")
    msg = result.get("message", "")
    summary = result.get("summary", "")
    if status == "error":
        return ""
    text = f"**Meeting Minutes**\n{msg}"
    if summary:
        text += f"\n\n**Summary:**\n{summary}"
    return text


def _format_email(action: str, result: dict) -> str:
    status = result.get("status", "")
    msg = result.get("message", "")
    if status == "error":
        return ""
    titles = {
        "draft_email": "Email Drafted",
        "send_email": "Email Sent",
        "read_email": "Email Read",
    }
    title = titles.get(action, "Email")
    return f"**{title}**\n{msg}"


def _format_calendar(action: str, result: dict) -> str:
    status = result.get("status", "")
    msg = result.get("message", "")
    if status == "error":
        return ""
    return f"**Calendar Event**\n{msg}"


def _format_generic(action: str, result: dict) -> str:
    status = result.get("status", "")
    msg = result.get("message", "")
    if status == "error" or not msg:
        return ""
    return f"**{action}**\n{msg}"


ACTION_FORMATTERS = {
    "note": _format_note,
    "note_start": _format_note_start,
    "meeting_minutes": _format_meeting,
    "draft_email": _format_email,
    "send_email": _format_email,
    "read_email": _format_email,
    "calendar_event": _format_calendar,
}
