"""Claude agent adapter — normalizes Claude Code / Anthropic API events."""

from __future__ import annotations

from typing import Any, Sequence

from .base import AgentAdapter, GovernanceEvent


class ClaudeAdapter(AgentAdapter):
    """Adapter for Claude/Anthropic agent event streams."""

    PROVIDER = "claude"

    # Claude tool name → semantic action class mapping
    TOOL_CLASS_MAP: dict[str, str] = {
        "Read": "filesystem_read",
        "Glob": "filesystem_read",
        "Grep": "filesystem_read",
        "Write": "filesystem_write",
        "Edit": "filesystem_write",
        "NotebookEdit": "filesystem_write",
        "Bash": "shell",
        "PowerShell": "shell",
        "StructuredOutput": "structured_result",
        "WebSearch": "network",
        "WebFetch": "network",
    }

    def normalize_events(
        self, raw_events: Sequence[dict[str, Any]]
    ) -> list[GovernanceEvent]:
        events: list[GovernanceEvent] = []
        for index, raw in enumerate(raw_events):
            event = self._normalize_one(raw, index)
            events.append(event)
        return events

    def _normalize_one(
        self, raw: dict[str, Any], index: int
    ) -> GovernanceEvent:
        event_type = str(raw.get("type", "unknown"))
        message = raw.get("message")
        tool_name = ""
        tool_input: dict[str, Any] = {}
        paths: list[str] = []

        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_name = str(block.get("name", ""))
                        inp = block.get("input")
                        if isinstance(inp, dict):
                            tool_input = dict(inp)
                        # Extract paths
                        for key in ("file_path", "path", "notebook_path", "pattern"):
                            val = tool_input.get(key)
                            if isinstance(val, str) and val:
                                paths.append(val)
                        break

        return GovernanceEvent(
            event_id=f"claude_{index}",
            provider=self.PROVIDER,
            event_type=event_type,
            tool_name=tool_name,
            tool_input=tool_input,
            paths=tuple(paths),
            metadata={"raw_type": event_type, "index": index},
        )

    def build_executor_command(
        self, task_spec: dict[str, Any], workspace: str
    ) -> list[str]:
        """Build a Claude Code executor invocation. (Reference adapter — requires Claude Code CLI.)"""
        return [
            "claude",
            "--workspace", workspace,
            "--task-spec", task_spec.get("task_id", ""),
        ]

    def build_reviewer_prompt(
        self, task_spec: dict[str, Any], execution_result: dict[str, Any]
    ) -> str:
        """Build a reviewer prompt. (Reference — real prompt comes from Skill integration.)"""
        return f"""Review the following agent execution:

Task: {task_spec.get('task_id')}
Type: {task_spec.get('task_type')}

Execution Result:
{execution_result.get('summary', 'No summary')}

Files changed: {execution_result.get('files_modified', [])}
Files created: {execution_result.get('files_created', [])}
Files deleted: {execution_result.get('files_deleted', [])}

Determine: ACCEPT / REWORK / REJECT"""
