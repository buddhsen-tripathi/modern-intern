"""Email agent — draft, send, read emails.

Currently a stub that stores drafts locally.
TODO: Integrate with Gmail API via OAuth2.
"""

import logging
import time

from src.agents.base import BaseAgent

log = logging.getLogger(__name__)


class EmailAgent(BaseAgent):
    def __init__(self):
        self._drafts: list[dict] = []
        self._current_draft: dict | None = None

    @property
    def name(self) -> str:
        return "Email"

    @property
    def current_draft(self) -> dict | None:
        return self._current_draft

    async def execute(self, params: dict, context: dict) -> dict:
        action = context.get("sub_action", "draft")

        if action == "draft":
            return self._draft(params)
        elif action == "send":
            return self._send(params)
        elif action == "read":
            return self._read(params)
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
            # Auto-generate subject from body
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

    def _send(self, params: dict) -> dict:
        if not self._current_draft:
            return {
                "status": "error",
                "error_type": "no_draft",
                "message": "No draft to send. Say 'draft email' first.",
            }

        draft = self._current_draft
        if not draft.get("to"):
            return {
                "status": "error",
                "error_type": "missing_recipient",
                "message": "Draft has no recipient. Who should I send it to?",
            }

        # TODO: actual Gmail API send
        log.info("Email sent (stub): to=%s subject=%s", draft["to"], draft["subject"])
        sent_draft = self._current_draft
        self._current_draft = None
        return {
            "status": "success",
            "message": f"Email sent to {sent_draft['to']}: \"{sent_draft['subject']}\"",
        }

    def _read(self, params: dict) -> dict:
        count = params.get("count", 5)
        # TODO: actual Gmail API read
        log.info("Read emails requested (stub): count=%d", count)
        return {
            "status": "success",
            "message": "Email reading not yet connected. Connect Gmail API to enable.",
        }
