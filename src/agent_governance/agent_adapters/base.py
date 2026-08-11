"""Abstract agent adapter interface — provider-agnostic core accepts generic events."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class GovernanceEvent:
    """A normalized governance event from any agent provider."""

    event_id: str
    provider: str
    event_type: str  # "tool_use", "model_text", "result", "user"
    tool_name: str
    tool_input: dict[str, Any]
    paths: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentAdapter(ABC):
    """Abstract interface for provider-specific event normalization.

    Implementations convert provider-specific event formats into
    the generic GovernanceEvent type used by the deterministic core.
    """

    @abstractmethod
    def normalize_events(
        self, raw_events: Sequence[dict[str, Any]]
    ) -> list[GovernanceEvent]:
        """Convert provider-specific events to normalized GovernanceEvents."""
        ...

    @abstractmethod
    def build_executor_command(
        self, task_spec: dict[str, Any], workspace: str
    ) -> list[str]:
        """Build the command to invoke the executor agent."""
        ...

    @abstractmethod
    def build_reviewer_prompt(
        self, task_spec: dict[str, Any], execution_result: dict[str, Any]
    ) -> str:
        """Build a reviewer prompt from task spec and execution result."""
        ...
