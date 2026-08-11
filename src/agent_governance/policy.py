"""Fail-closed static policy engine with four-category path enforcement."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .runtime_utils import sha256_value
from .task_spec import (
    TaskSpec,
    build_task_spec,
    normalize_repo_path,
    scope_contains,
)


@dataclass(frozen=True)
class PolicyViolation:
    """A single policy violation with code, message, and offending value."""

    code: str
    message: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "value": self.value}


@dataclass(frozen=True)
class PolicyResult:
    """Result of evaluating a policy against a TaskSpec and event stream."""

    valid: bool
    violations: tuple[PolicyViolation, ...]
    policy_hash: str
    task_spec_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "violations": [v.to_dict() for v in self.violations],
            "policy_hash": self.policy_hash,
            "task_spec_hash": self.task_spec_hash,
        }


@dataclass(frozen=True)
class StaticPolicy:
    """Fail-closed static policy loaded from a JSON configuration."""

    raw: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "StaticPolicy":
        """Load policy from a JSON file."""
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StaticPolicy":
        """Create policy from an already-loaded dict."""
        return cls(data)

    @property
    def content_hash(self) -> str:
        """Deterministic hash of policy content."""
        return sha256_value(self.raw)

    @property
    def forbidden_path_patterns(self) -> list[str]:
        return list(self.raw.get("global_forbidden_path_patterns", []))

    @property
    def forbidden_command_patterns(self) -> list[str]:
        return list(self.raw.get("global_forbidden_command_patterns", []))

    def validate_task_spec(
        self, task_spec_or_dict: TaskSpec | dict[str, Any]
    ) -> PolicyResult:
        """Validate a TaskSpec against this policy."""
        violations: list[PolicyViolation] = []

        if isinstance(task_spec_or_dict, dict):
            try:
                task_spec = build_task_spec(task_spec_or_dict)
            except Exception as exc:
                violations.append(
                    PolicyViolation(
                        code="TASKSPEC_INVALID",
                        message=f"TaskSpec failed structural validation: {exc}",
                        value=str(task_spec_or_dict.get("task_id", "unknown")),
                    )
                )
                return PolicyResult(
                    valid=False,
                    violations=tuple(violations),
                    policy_hash=self.content_hash,
                    task_spec_hash="",
                )
        else:
            task_spec = task_spec_or_dict

        violations.extend(self._validate_limits(task_spec))
        violations.extend(self._validate_modes(task_spec))
        violations.extend(
            self._evaluate_paths(task_spec.read_paths, "read_paths")
        )
        violations.extend(
            self._evaluate_paths(task_spec.write_paths, "write_paths")
        )
        violations.extend(
            self._evaluate_commands(task_spec.allowed_commands, "allowed_commands")
        )
        violations.extend(self._validate_disjoint_rules(task_spec))

        return PolicyResult(
            valid=len(violations) == 0,
            violations=tuple(violations),
            policy_hash=self.content_hash,
            task_spec_hash=task_spec.content_hash,
        )

    def validate_path(
        self, path: str, task_spec: TaskSpec, action: str
    ) -> tuple[bool, str]:
        """Validate a single path access against policy and TaskSpec.

        Returns (allowed, reason).
        """
        normalized = normalize_repo_path(path)

        # Global forbidden patterns
        for pattern in self.forbidden_path_patterns:
            if _matches_path(pattern, normalized):
                return False, f"path {normalized} matches global forbidden pattern {pattern}"

        # TaskSpec scope check
        return task_spec.validate_path_access(normalized, action)

    def _evaluate_paths(
        self, paths: Iterable[str], context: str
    ) -> list[PolicyViolation]:
        violations: list[PolicyViolation] = []
        for path in paths:
            normalized = normalize_repo_path(path)
            for pattern in self.forbidden_path_patterns:
                if _matches_path(pattern, normalized):
                    violations.append(
                        PolicyViolation(
                            code="FORBIDDEN_PATH",
                            message=f"{context} contains a globally forbidden path pattern",
                            value=f"{path} matches {pattern}",
                        )
                    )
        return violations

    def _evaluate_commands(
        self, commands: Iterable[str], context: str
    ) -> list[PolicyViolation]:
        violations: list[PolicyViolation] = []
        for command in commands:
            command_norm = " ".join(command.lower().split())
            for pattern in self.forbidden_command_patterns:
                if pattern.lower() in command_norm:
                    violations.append(
                        PolicyViolation(
                            code="FORBIDDEN_COMMAND",
                            message=f"{context} contains a globally forbidden command pattern",
                            value=f"{command} contains {pattern}",
                        )
                    )
        return violations

    def _validate_limits(self, task_spec: TaskSpec) -> list[PolicyViolation]:
        violations: list[PolicyViolation] = []
        limits = self.raw.get("limits", {})
        for key, maximum in limits.items():
            actual = getattr(task_spec, key, None)
            if isinstance(actual, int) and actual > maximum:
                violations.append(
                    PolicyViolation(
                        code="LIMIT_EXCEEDED",
                        message=f"{key} exceeds global limit {maximum}",
                        value=str(actual),
                    )
                )
        return violations

    def _validate_modes(self, task_spec: TaskSpec) -> list[PolicyViolation]:
        violations: list[PolicyViolation] = []
        required_modes = self.raw.get("required_task_modes", {})
        for key, allowed_values in required_modes.items():
            actual = getattr(task_spec, key, None)
            if actual not in allowed_values:
                violations.append(
                    PolicyViolation(
                        code="MODE_NOT_ALLOWED",
                        message=f"{key} must be one of {allowed_values}",
                        value=str(actual),
                    )
                )
        return violations

    def _validate_disjoint_rules(self, task_spec: TaskSpec) -> list[PolicyViolation]:
        violations: list[PolicyViolation] = []
        allowed = {normalize_repo_path(p) for p in task_spec.read_paths}
        allowed.update(normalize_repo_path(p) for p in task_spec.write_paths)
        forbidden = {normalize_repo_path(p) for p in task_spec.forbidden_paths}
        overlap = sorted(allowed & forbidden)
        for path in overlap:
            violations.append(
                PolicyViolation(
                    code="PATH_RULE_CONFLICT",
                    message="A path cannot be both allowed and forbidden",
                    value=path,
                )
            )
        return violations


def _matches_path(pattern: str, path: str) -> bool:
    """Check if a normalized path matches a glob pattern."""
    normalized = pattern.replace("\\", "/").lower()
    # Strip a leading "./" prefix only (not individual chars)
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if fnmatch.fnmatchcase(path, normalized):
        return True
    if normalized.startswith("**/"):
        return fnmatch.fnmatchcase(path, normalized[3:])
    return False
