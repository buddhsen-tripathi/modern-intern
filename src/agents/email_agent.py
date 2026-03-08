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

    async def execute(self, params: dict, context: dict) -> dict:
        # Determine sub-action from the action_type passed by orchestrator
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
        draft = {
            "to": params.get("to", ""),
            "subject": params.get("subject", ""),
            "body": params.get("body", ""),
            "timestamp": time.time(),
        }
        self._current_draft = draft
        self._drafts.append(draft)
        log.info("Email drafted: to=%s subject=%s", draft["to"], draft["subject"])
        return {
            "status": "success",
            "message": f"Draft created: \"{draft['subject']}\" to {draft['to'] or 'TBD'}",
            "draft": draft,
        }

    def _send(self, params: dict) -> dict:
        if not self._current_draft:
            return {"status": "error", "message": "No draft to send. Draft an email first."}

        draft = self._current_draft
        if not draft.get("to"):
            return {"status": "error", "message": "Draft has no recipient. Specify who to send to."}

        # TODO: actual Gmail API send
        log.info("Email sent (stub): to=%s subject=%s", draft["to"], draft["subject"])
        self._current_draft = None
        return {
            "status": "success",
            "message": f"Email sent to {draft['to']}: \"{draft['subject']}\"",
        }

    def _read(self, params: dict) -> dict:
        count = params.get("count", 5)
        # TODO: actual Gmail API read
        log.info("Read emails requested (stub): count=%d", count)
        return {
            "status": "success",
            "message": f"Email reading not yet connected. Connect Gmail API to enable.",
        }
