"""TaskSpec v2 — typed task specification with four-category path semantics.

read_paths: readable scope
write_paths: writable scope (must be subset of read_paths)
immutable_read_paths: readable but never writable
forbidden_paths: always wins, blocks both read and write
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .runtime_utils import normalize_repo_path, sha256_value

TASK_SPEC_VERSION = 2


class TaskSpecValidationError(ValueError):
    """Raised when a TaskSpec fails structural or semantic validation."""


@dataclass(frozen=True)
class TaskSpec:
    """Immutable TaskSpec v2 with four-category path semantics."""

    task_id: str
    task_type: str
    base_commit: str

    read_paths: tuple[str, ...]
    write_paths: tuple[str, ...]
    immutable_read_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()

    allowed_commands: tuple[str, ...] = ()
    forbidden_commands: tuple[str, ...] = ()

    required_tests: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    evidence_requirements: tuple[str, ...] = ()

    max_execution_minutes: int = 30
    max_agent_turns: int = 50
    max_rework_cycles: int = 3

    execution_mode: str = "sequential"

    _content_hash: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.task_id:
            raise TaskSpecValidationError("task_id must be non-empty")
        if not self.task_type:
            raise TaskSpecValidationError("task_type must be non-empty")
        if not self.base_commit or len(self.base_commit) != 40:
            raise TaskSpecValidationError("base_commit must be a 40-char hex SHA")

    @property
    def content_hash(self) -> str:
        """Deterministic hash of the TaskSpec content."""
        if self._content_hash is None:
            object.__setattr__(self, "_content_hash", sha256_value(self.to_dict()))
        return self._content_hash

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict (sorted keys for deterministic hashing)."""
        result: dict[str, Any] = {
            "task_spec_version": TASK_SPEC_VERSION,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "base_commit": self.base_commit,
            "read_paths": sorted(self.read_paths),
            "write_paths": sorted(self.write_paths),
            "immutable_read_paths": sorted(self.immutable_read_paths),
            "forbidden_paths": sorted(self.forbidden_paths),
            "allowed_commands": sorted(self.allowed_commands),
            "forbidden_commands": sorted(self.forbidden_commands),
            "required_tests": sorted(self.required_tests),
            "expected_outputs": sorted(self.expected_outputs),
            "evidence_requirements": sorted(self.evidence_requirements),
            "max_execution_minutes": self.max_execution_minutes,
            "max_agent_turns": self.max_agent_turns,
            "max_rework_cycles": self.max_rework_cycles,
            "execution_mode": self.execution_mode,
        }
        return result

    def is_path_readable(self, path: str) -> bool:
        """Check if a path is within the read scope."""
        normalized = normalize_repo_path(path)
        if _path_matches_any(normalized, self.forbidden_paths):
            return False
        return _path_matches_any(normalized, self.read_paths)

    def is_path_writable(self, path: str) -> bool:
        """Check if a path is within the write scope."""
        normalized = normalize_repo_path(path)
        if _path_matches_any(normalized, self.forbidden_paths):
            return False
        if _path_matches_any(normalized, self.immutable_read_paths):
            return False
        return _path_matches_any(normalized, self.write_paths)

    def validate_path_access(
        self, path: str, action: str
    ) -> tuple[bool, str]:
        """Validate access for a path and action type.

        Returns (allowed, reason).
        """
        normalized = normalize_repo_path(path)

        if _path_matches_any(normalized, self.forbidden_paths):
            return False, f"path {normalized} is in forbidden_paths"

        if action in ("read", "glob", "grep"):
            if not _path_matches_any(normalized, self.read_paths):
                return False, f"path {normalized} is outside read_paths"
            return True, "ok"

        if action in ("write", "edit", "create", "delete"):
            if _path_matches_any(normalized, self.immutable_read_paths):
                return False, f"path {normalized} is in immutable_read_paths"
            if not _path_matches_any(normalized, self.write_paths):
                return False, f"path {normalized} is outside write_paths"
            return True, "ok"

        return False, f"unknown action type: {action}"


def _path_matches_any(path: str, scopes: tuple[str, ...]) -> bool:
    """Check if a normalized path is covered by any scope."""
    for scope in scopes:
        if path == scope or path.startswith(scope + "/"):
            return True
    return False


def scope_contains(scope: str, path: str) -> bool:
    """Return True when a scope prefix contains a path."""
    return path == scope or path.startswith(scope + "/")


def scopes_overlap(left: str, right: str) -> bool:
    """Return True when two scopes overlap."""
    return scope_contains(left, right) or scope_contains(right, left)


def normalize_scope_list(
    value: Any, label: str, *, require_nonempty: bool = False
) -> tuple[list[str], list[str]]:
    """Normalize and validate a scope list, returning (paths, errors)."""
    errors: list[str] = []
    normalized: list[str] = []
    if not isinstance(value, list):
        return [], [f"{label} must be an array"]
    if require_nonempty and not value:
        errors.append(f"{label} must be a non-empty array")
    for index, raw in enumerate(value):
        try:
            path = normalize_repo_path(str(raw))
        except ValueError as exc:
            errors.append(f"{label}[{index}] invalid: {exc}")
            continue
        if path in normalized:
            errors.append(f"{label} contains duplicate path: {path}")
        else:
            normalized.append(path)
    return normalized, errors


def validate_task_spec_structure(task: dict[str, Any]) -> tuple[dict[str, list[str]], list[str]]:
    """Validate TaskSpec v2 scope structure.

    Returns ({scope_name: paths}, errors).
    """
    errors: list[str] = []
    if task.get("task_spec_version") != TASK_SPEC_VERSION:
        errors.append(f"task_spec_version must equal {TASK_SPEC_VERSION}")
    if "allowed_paths" in task:
        errors.append(
            "legacy allowed_paths is ambiguous and rejected; use TaskSpec v2 scopes"
        )

    read_paths, current = normalize_scope_list(
        task.get("read_paths"), "read_paths", require_nonempty=True
    )
    errors.extend(current)
    write_paths, current = normalize_scope_list(
        task.get("write_paths"), "write_paths", require_nonempty=True
    )
    errors.extend(current)
    immutable_paths, current = normalize_scope_list(
        task.get("immutable_read_paths"), "immutable_read_paths", require_nonempty=False
    )
    errors.extend(current)
    forbidden_paths, current = normalize_scope_list(
        task.get("forbidden_paths"), "forbidden_paths", require_nonempty=False
    )
    errors.extend(current)

    # write_paths must be subset of read_paths
    for path in write_paths:
        if not any(scope_contains(rs, path) for rs in read_paths):
            errors.append(f"write_paths is not a subset of read_paths: {path}")

    # immutable_read_paths must be subset of read_paths, disjoint from write_paths
    for path in immutable_paths:
        if not any(scope_contains(rs, path) for rs in read_paths):
            errors.append(f"immutable_read_paths is not a subset of read_paths: {path}")
        if any(scopes_overlap(path, wp) for wp in write_paths):
            errors.append(f"immutable_read_paths overlaps write_paths: {path}")

    # forbidden_paths always win — must not overlap read or write scopes
    for denied in forbidden_paths:
        if any(scopes_overlap(denied, p) for p in read_paths):
            errors.append(f"forbidden_paths overlaps read_paths: {denied}")
        if any(scopes_overlap(denied, p) for p in write_paths):
            errors.append(f"forbidden_paths overlaps write_paths: {denied}")

    if errors:
        return {}, errors

    return {
        "read_paths": read_paths,
        "write_paths": write_paths,
        "immutable_read_paths": immutable_paths,
        "forbidden_paths": forbidden_paths,
    }, []


def build_task_spec(raw: dict[str, Any]) -> TaskSpec:
    """Build a validated TaskSpec from a raw dict."""
    scopes, errors = validate_task_spec_structure(raw)
    if errors:
        raise TaskSpecValidationError("\n".join(errors))
    return TaskSpec(
        task_id=raw["task_id"],
        task_type=raw["task_type"],
        base_commit=raw["base_commit"],
        read_paths=tuple(sorted(scopes["read_paths"])),
        write_paths=tuple(sorted(scopes["write_paths"])),
        immutable_read_paths=tuple(sorted(scopes["immutable_read_paths"])),
        forbidden_paths=tuple(sorted(scopes["forbidden_paths"])),
        allowed_commands=tuple(sorted(raw.get("allowed_commands", []))),
        forbidden_commands=tuple(sorted(raw.get("forbidden_commands", []))),
        required_tests=tuple(sorted(raw.get("required_tests", []))),
        expected_outputs=tuple(sorted(raw.get("expected_outputs", []))),
        evidence_requirements=tuple(sorted(raw.get("evidence_requirements", []))),
        max_execution_minutes=raw.get("max_execution_minutes", 30),
        max_agent_turns=raw.get("max_agent_turns", 50),
        max_rework_cycles=raw.get("max_rework_cycles", 3),
        execution_mode=raw.get("execution_mode", "sequential"),
    )
