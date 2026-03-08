"""Search agent — answers queries with a 2-3 sentence summary.

Uses Gemini text model to generate concise answers.
"""

import logging

from google import genai
from google.genai import types

from src.agents.base import BaseAgent
from src.config import BRAIN_MODEL

log = logging.getLogger(__name__)


class SearchAgent(BaseAgent):
    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)

    @property
    def name(self) -> str:
        return "Search"

    async def execute(self, params: dict, context: dict) -> dict:
        query = params.get("query", "").strip()
        if not query:
            return {
                "status": "error",
                "error_type": "missing_query",
                "message": "What do you want me to search for?",
            }

        try:
            response = await self._client.aio.models.generate_content(
                model=BRAIN_MODEL,
                contents=(
                    f"Answer the following query in exactly 2-3 sentences. "
                    f"Be factual, concise, and informative. No filler.\n\n"
                    f"Query: {query}"
                ),
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            summary = response.text.strip()
            log.info("Search result for '%s': %s", query[:50], summary[:100])
            return {
                "status": "success",
                "message": summary,
                "query": query,
            }
        except Exception as e:
            log.error("Search failed: %s", e)
            return {"status": "error", "message": f"Search failed: {e}"}
