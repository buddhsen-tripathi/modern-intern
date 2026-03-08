"""Telegram Bot API integration — sends action results to a Telegram chat.

Uses raw HTTP via aiohttp (zero extra dependencies).
Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment.
"""

import logging
import os

import aiohttp

log = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class TelegramService:
    def __init__(self):
        self._token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self._session: aiohttp.ClientSession | None = None

        if not self._token or not self._chat_id:
            log.warning(
                "Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
            )

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a text message to the configured Telegram chat."""
        if not self.enabled:
            return False

        url = f"{TELEGRAM_API}/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        try:
            session = await self._get_session()
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    log.info("Telegram message sent")
                    return True
                else:
                    body = await resp.text()
                    log.error("Telegram API error %d: %s", resp.status, body[:200])
                    return False
        except Exception as e:
            log.error("Telegram send failed: %s", e)
            return False

    async def send_action_result(self, action: str, result: dict):
        """Format and send an action result to Telegram."""
        formatter = ACTION_FORMATTERS.get(action, _format_generic)
        text = formatter(action, result)
        if text:
            await self.send_message(text)


# -- Formatters for each action type --

def _format_note(action: str, result: dict) -> str:
    status = result.get("status", "")
    msg = result.get("message", "")
    total = result.get("total_notes", "")

    if status == "error":
        return ""

    return (
        f"<b>📝 Note Saved</b>\n"
        f"{_escape(msg)}\n"
        f"<i>Total notes: {total}</i>"
    )


def _format_note_start(action: str, result: dict) -> str:
    if result.get("status") == "success":
        return "<b>📝 Note Recording Started</b>\nListening..."
    return ""


def _format_meeting(action: str, result: dict) -> str:
    status = result.get("status", "")
    msg = result.get("message", "")
    summary = result.get("summary", "")

    if status == "error":
        return ""

    text = f"<b>📋 Meeting Minutes</b>\n{_escape(msg)}"
    if summary:
        text += f"\n\n<b>Summary:</b>\n{_escape(summary)}"
    return text


def _format_email(action: str, result: dict) -> str:
    status = result.get("status", "")
    msg = result.get("message", "")

    if status == "error":
        return ""

    icons = {"draft_email": "✉️ Email Drafted", "send_email": "📨 Email Sent", "read_email": "📩 Email Read"}
    title = icons.get(action, "✉️ Email")
    return f"<b>{title}</b>\n{_escape(msg)}"


def _format_calendar(action: str, result: dict) -> str:
    status = result.get("status", "")
    msg = result.get("message", "")

    if status == "error":
        return ""

    return f"<b>📅 Calendar Event</b>\n{_escape(msg)}"


def _format_generic(action: str, result: dict) -> str:
    status = result.get("status", "")
    msg = result.get("message", "")

    if status == "error" or not msg:
        return ""

    return f"<b>✅ {_escape(action)}</b>\n{_escape(msg)}"


def _escape(text: str) -> str:
    """Escape HTML special characters for Telegram."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


ACTION_FORMATTERS = {
    "note": _format_note,
    "note_start": _format_note_start,
    "meeting_minutes": _format_meeting,
    "draft_email": _format_email,
    "send_email": _format_email,
    "read_email": _format_email,
    "calendar_event": _format_calendar,
}
