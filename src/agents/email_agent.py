"""Email agent — draft, send, read emails via Gmail SMTP/IMAP.

Requires GMAIL_ADDRESS and GMAIL_APP_PASSWORD in environment.
"""

import logging
import os
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib
import aioimaplib
import email as email_lib
from email.header import decode_header as _decode_header

from src.agents.base import BaseAgent

log = logging.getLogger(__name__)


class EmailAgent(BaseAgent):
    def __init__(self):
        self._drafts: list[dict] = []
        self._current_draft: dict | None = None
        self._gmail_address = os.getenv("GMAIL_ADDRESS", "")
        self._gmail_password = os.getenv("GMAIL_APP_PASSWORD", "")

        if not self._gmail_address or not self._gmail_password:
            log.warning("Gmail not configured — set GMAIL_ADDRESS and GMAIL_APP_PASSWORD")

    @property
    def name(self) -> str:
        return "Email"

    @property
    def enabled(self) -> bool:
        return bool(self._gmail_address and self._gmail_password)

    @property
    def current_draft(self) -> dict | None:
        return self._current_draft

    async def execute(self, params: dict, context: dict) -> dict:
        action = context.get("sub_action", "draft")

        if action == "draft":
            return self._draft(params)
        elif action == "send":
            return await self._send(params)
        elif action == "read":
            return await self._read(params)
        else:
            return {"status": "error", "message": f"Unknown email action: {action}"}

    def _draft(self, params: dict) -> dict:
        to = params.get("to", "").strip()
        subject = params.get("subject", "").strip()
        body = params.get("body", "").strip()

        if not to:
            return {
                "status": "error",
                "error_type": "missing_recipient",
                "message": "Who should I send this email to?",
            }

        if not subject and not body:
            return {
                "status": "error",
                "error_type": "missing_content",
                "message": f"Draft to {to} — what should the email say?",
            }

        if not subject:
            subject = body[:40] + ("..." if len(body) > 40 else "")

        draft = {
            "to": to,
            "subject": subject,
            "body": body,
            "timestamp": time.time(),
        }
        self._current_draft = draft
        self._drafts.append(draft)
        log.info("Email drafted: to=%s subject=%s", draft["to"], draft["subject"])
        return {
            "status": "success",
            "message": f"Draft ready — to {to}, subject: \"{subject}\". Say 'send email' to send.",
            "draft": draft,
        }

    async def _send(self, params: dict) -> dict:
        if not self._current_draft:
            return {
                "status": "error",
                "error_type": "no_draft",
                "message": "No draft to send. Say 'draft email' first.",
            }

        if not self.enabled:
            return {"status": "error", "message": "Gmail not configured."}

        draft = self._current_draft
        if not draft.get("to"):
            return {
                "status": "error",
                "error_type": "missing_recipient",
                "message": "Draft has no recipient. Who should I send it to?",
            }

        to_addr = draft["to"]
        # If recipient is a name (not an email), we can't send
        if "@" not in to_addr:
            return {
                "status": "error",
                "error_type": "missing_email",
                "message": f"I need an email address for {to_addr}. What's their email?",
            }

        try:
            msg = MIMEMultipart()
            msg["From"] = self._gmail_address
            msg["To"] = to_addr
            msg["Subject"] = draft.get("subject", "(no subject)")
            msg.attach(MIMEText(draft.get("body", ""), "plain"))

            smtp = aiosmtplib.SMTP(hostname="smtp.gmail.com", port=587, start_tls=True)
            await smtp.connect()
            await smtp.login(self._gmail_address, self._gmail_password)
            await smtp.send_message(msg)
            await smtp.quit()

            log.info("Email sent: to=%s subject=%s", to_addr, draft.get("subject"))
            self._current_draft = None
            return {
                "status": "success",
                "message": f"Email sent to {to_addr}.",
            }
        except Exception as e:
            log.error("Email send failed: %s", e)
            return {"status": "error", "message": f"Failed to send email: {e}"}

    async def _read(self, params: dict) -> dict:
        if not self.enabled:
            return {"status": "error", "message": "Gmail not configured."}

        count = min(params.get("count", 5), 10)

        try:
            imap = aioimaplib.IMAP4_SSL(host="imap.gmail.com")
            await imap.wait_hello_from_server()
            await imap.login(self._gmail_address, self._gmail_password)
            await imap.select("INBOX")

            # Get latest message IDs
            _, data = await imap.search("ALL")
            msg_ids = data[0].split()
            if not msg_ids:
                await imap.logout()
                return {"status": "success", "message": "Inbox is empty."}

            recent_ids = msg_ids[-count:]
            recent_ids.reverse()

            summaries = []
            for msg_id in recent_ids:
                _, msg_data = await imap.fetch(msg_id.decode(), "(RFC822.HEADER)")
                if msg_data and len(msg_data) > 1:
                    raw = msg_data[1]
                    if isinstance(raw, tuple):
                        raw = raw[1]
                    if isinstance(raw, bytearray):
                        raw = bytes(raw)
                    elif isinstance(raw, str):
                        raw = raw.encode()
                    parsed = email_lib.message_from_bytes(raw)
                    frm = self._decode_header(parsed.get("From", "unknown"))
                    subj = self._decode_header(parsed.get("Subject", "(no subject)"))
                    summaries.append(f"From {frm}: {subj}")

            await imap.logout()

            if summaries:
                listing = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(summaries))
                return {
                    "status": "success",
                    "message": f"Latest {len(summaries)} emails:\n{listing}",
                }
            else:
                return {"status": "success", "message": "No recent emails found."}

        except Exception as e:
            log.error("Email read failed: %s", e)
            return {"status": "error", "message": f"Failed to read emails: {e}"}

    @staticmethod
    def _decode_header(value: str) -> str:
        """Decode RFC 2047 encoded email headers."""
        parts = _decode_header(value)
        decoded = []
        for data, charset in parts:
            if isinstance(data, bytes):
                decoded.append(data.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(data)
        return " ".join(decoded)
