"""Base agent interface."""

from abc import ABC, abstractmethod


class BaseAgent(ABC):
    """Base class for all Silas agents."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable agent name."""

    @abstractmethod
    async def execute(self, params: dict, context: dict) -> dict:
        """Execute the agent task.

        Args:
            params: Action parameters from Gemini (parsed from <<ACTION>> tag).
            context: Session context (recent observations, etc).

        Returns:
            Result dict with at least {"status": "success"|"error", "message": "..."}.
        """
