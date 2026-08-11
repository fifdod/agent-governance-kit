"""Event policy classifier — normalizes agent tool events into action classes.

Fail-closed: unknown filesystem-relevant actions are violations.
Pathless filesystem actions are violations.
Structured result transport is explicitly categorized.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .task_spec import TaskSpec, normalize_repo_path


class EventClass(str, Enum):
    """Normalized event action classes."""

    MODEL_TEXT = "MODEL_TEXT"
    PROTOCOL_EVENT = "PROTOCOL_EVENT"
    STRUCTURED_RESULT_TRANSPORT = "STRUCTURED_RESULT_TRANSPORT"
    FILESYSTEM_READ = "FILESYSTEM_READ"
    FILESYSTEM_WRITE = "FILESYSTEM_WRITE"
    SHELL = "SHELL"
    NETWORK = "NETWORK"
    NON_FILESYSTEM = "NON_FILESYSTEM"
    UNKNOWN = "UNKNOWN"


# Tool name → EventClass mapping (provider-agnostic)
READ_TOOLS = frozenset({"Read", "Glob", "Grep"})
WRITE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
SHELL_TOOLS = frozenset({"Bash", "Shell", "PowerShell", "Cmd"})
NETWORK_TOOLS = frozenset({"WebSearch", "WebFetch", "Browser"})

# Tools that are always forbidden in restricted executor mode
ALWAYS_FORBIDDEN_TOOLS = SHELL_TOOLS | NETWORK_TOOLS

# Executor structured report fields
EXECUTOR_REPORT_FIELDS = frozenset(
    {"files_created", "files_modified", "files_deleted", "commands_executed", "summary"}
)


@dataclass(frozen=True)
class NormalizedEvent:
    """A single normalized agent event."""

    event_id: str
    provider: str
    tool_name: str
    action_class: EventClass
    paths: tuple[str, ...]
    command: str | None
    raw_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EventPolicyViolation:
    """A violation found during event stream evaluation."""

    event_id: str
    code: str
    message: str
    tool_name: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class EventPolicyResult:
    """Result of evaluating event policy against an event stream."""

    valid: bool
    violations: tuple[EventPolicyViolation, ...]
    event_count: int
    structured_result_transport_count: int
    filesystem_read_count: int
    filesystem_write_count: int
    shell_count: int
    network_count: int
    unknown_count: int


def classify_tool_name(name: str) -> EventClass:
    """Classify a tool by name into its event class."""
    if name in READ_TOOLS:
        return EventClass.FILESYSTEM_READ
    if name in WRITE_TOOLS:
        return EventClass.FILESYSTEM_WRITE
    if name in SHELL_TOOLS:
        return EventClass.SHELL
    if name in NETWORK_TOOLS:
        return EventClass.NETWORK
    if name == "StructuredOutput":
        return EventClass.STRUCTURED_RESULT_TRANSPORT
    return EventClass.UNKNOWN


def classify_non_tool_event(event: Mapping[str, Any]) -> EventClass:
    """Classify a non-tool event (model text, protocol events)."""
    message = event.get("message")
    if event.get("type") == "assistant" and isinstance(message, Mapping):
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(item, Mapping) and item.get("type") in {"text", "thinking"}
            for item in content
        ):
            return EventClass.MODEL_TEXT
    return EventClass.PROTOCOL_EVENT


def extract_paths_from_event(event: Mapping[str, Any]) -> list[str]:
    """Extract file paths from a tool event's input."""
    message = event.get("message")
    if not isinstance(message, Mapping):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []

    paths: list[str] = []
    for block in content:
        if not isinstance(block, Mapping) or block.get("type") != "tool_use":
            continue
        payload = block.get("input")
        if not isinstance(payload, Mapping):
            continue
        # Common path fields
        for key in ("file_path", "path", "notebook_path"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                paths.append(value)
        # Glob pattern is a path-like field
        pattern = payload.get("pattern")
        if isinstance(pattern, str) and pattern:
            paths.append(pattern)
    return paths


def normalize_event(
    event: Mapping[str, Any],
    provider: str = "generic",
    event_id: str | None = None,
) -> NormalizedEvent:
    """Normalize a raw agent event into a NormalizedEvent."""
    raw_type = str(event.get("type", "unknown"))
    message = event.get("message")
    tool_name = ""

    if isinstance(message, Mapping):
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "tool_use":
                    tool_name = str(block.get("name", ""))
                    break

    if tool_name:
        action_class = classify_tool_name(tool_name)
    else:
        action_class = classify_non_tool_event(event)

    paths = tuple(extract_paths_from_event(event))

    command = None
    if action_class == EventClass.SHELL and isinstance(message, Mapping):
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "tool_use":
                    inp = block.get("input", {})
                    if isinstance(inp, Mapping):
                        command = str(inp.get("command", ""))

    return NormalizedEvent(
        event_id=event_id or f"evt_{hash(str(event))}",
        provider=provider,
        tool_name=tool_name,
        action_class=action_class,
        paths=paths,
        command=command,
        raw_type=raw_type,
    )


def evaluate_event_stream(
    events: Sequence[Mapping[str, Any]],
    task_spec: TaskSpec,
    *,
    workspace_root: str | Path,
    allowed_tools: frozenset[str] | None = None,
) -> EventPolicyResult:
    """Evaluate an event stream against a TaskSpec and policy.

    Fail-closed rules:
    - Unknown tools are violations
    - Pathless filesystem actions are violations
    - Out-of-scope reads/writes are violations
    - Shell/network tools are violations unless explicitly allowed
    """
    violations: list[EventPolicyViolation] = []
    counts: dict[EventClass, int] = {
        c: 0 for c in EventClass
    }
    structured_count = 0
    workspace = Path(workspace_root).resolve()

    for index, raw_event in enumerate(events):
        normalized = normalize_event(raw_event, event_id=f"evt_{index}")

        if normalized.action_class in (
            EventClass.FILESYSTEM_READ,
            EventClass.FILESYSTEM_WRITE,
        ):
            counts[normalized.action_class] += 1
        elif normalized.action_class == EventClass.STRUCTURED_RESULT_TRANSPORT:
            structured_count += 1
            counts[EventClass.STRUCTURED_RESULT_TRANSPORT] += 1
        elif normalized.action_class == EventClass.SHELL:
            counts[EventClass.SHELL] += 1
        elif normalized.action_class == EventClass.NETWORK:
            counts[EventClass.NETWORK] += 1
        elif normalized.action_class == EventClass.UNKNOWN:
            counts[EventClass.UNKNOWN] += 1
        else:
            continue

        # --- Fail-closed checks ---

        # Unknown tools are violations
        if normalized.action_class == EventClass.UNKNOWN:
            violations.append(
                EventPolicyViolation(
                    event_id=normalized.event_id,
                    code="UNKNOWN_TOOL",
                    message=f"Unknown tool: {normalized.tool_name}",
                    tool_name=normalized.tool_name,
                    paths=normalized.paths,
                )
            )
            continue

        # Shell and network are violations unless explicitly allowed
        if normalized.action_class in (EventClass.SHELL, EventClass.NETWORK):
            if allowed_tools and normalized.tool_name in allowed_tools:
                continue
            violations.append(
                EventPolicyViolation(
                    event_id=normalized.event_id,
                    code="FORBIDDEN_TOOL_CLASS",
                    message=f"Tool class {normalized.action_class.value} not allowed",
                    tool_name=normalized.tool_name,
                    paths=normalized.paths,
                )
            )
            continue

        # Pathless filesystem actions are violations
        if normalized.action_class in (
            EventClass.FILESYSTEM_READ,
            EventClass.FILESYSTEM_WRITE,
        ):
            if not normalized.paths:
                violations.append(
                    EventPolicyViolation(
                        event_id=normalized.event_id,
                        code="PATHLESS_FILESYSTEM_ACTION",
                        message="Filesystem action has no deterministic path",
                        tool_name=normalized.tool_name,
                        paths=(),
                    )
                )
                continue

            # Validate all paths against scope
            for raw_path in normalized.paths:
                try:
                    norm_path = normalize_repo_path(raw_path)
                except ValueError:
                    violations.append(
                        EventPolicyViolation(
                            event_id=normalized.event_id,
                            code="INVALID_PATH",
                            message=f"Path is not a valid repo-relative path: {raw_path}",
                            tool_name=normalized.tool_name,
                            paths=(raw_path,),
                        )
                    )
                    continue

                action = "read" if normalized.action_class == EventClass.FILESYSTEM_READ else "write"
                allowed, reason = task_spec.validate_path_access(norm_path, action)
                if not allowed:
                    violations.append(
                        EventPolicyViolation(
                            event_id=normalized.event_id,
                            code="OUT_OF_SCOPE" if "outside" in reason else "FORBIDDEN_PATH",
                            message=reason,
                            tool_name=normalized.tool_name,
                            paths=(norm_path,),
                        )
                    )

    return EventPolicyResult(
        valid=len(violations) == 0,
        violations=tuple(violations),
        event_count=len(events),
        structured_result_transport_count=structured_count,
        filesystem_read_count=counts[EventClass.FILESYSTEM_READ],
        filesystem_write_count=counts[EventClass.FILESYSTEM_WRITE],
        shell_count=counts[EventClass.SHELL],
        network_count=counts[EventClass.NETWORK],
        unknown_count=counts[EventClass.UNKNOWN],
    )
