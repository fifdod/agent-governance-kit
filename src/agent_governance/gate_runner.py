"""Deterministic gate runner — named checks with PASS/FAIL/SKIP status.

Fail-closed: a required gate that cannot execute must fail rather than silently skip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True)
class GateResult:
    """Result of a single deterministic gate check."""

    name: str
    status: GateStatus
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == GateStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "reason": self.reason,
            "evidence": self.evidence,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class GateRunnerResult:
    """Aggregate result from running all gates."""

    all_pass: bool
    total: int
    passed: int
    failed: int
    skipped: int
    failed_gate_names: tuple[str, ...]
    gates: tuple[GateResult, ...]
    verdict: str  # "ACCEPT" or "REJECT"

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_pass": self.all_pass,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "failed_gate_names": list(self.failed_gate_names),
            "gates": [g.to_dict() for g in self.gates],
            "verdict": self.verdict,
        }


class GateRunner:
    """Runs a set of deterministic gates and produces a stable final verdict."""

    def __init__(self, fail_closed: bool = True):
        self._gates: list[tuple[str, Callable[[], GateResult], bool]] = []
        self._fail_closed = fail_closed

    def add_gate(
        self,
        name: str,
        check: Callable[[], GateResult],
        required: bool = True,
    ) -> None:
        """Register a gate.

        Args:
            name: Gate name.
            check: Callable that returns a GateResult.
            required: If True, failure blocks acceptance.
        """
        self._gates.append((name, check, required))

    def run(self) -> GateRunnerResult:
        """Execute all registered gates and produce an aggregate result."""
        results: list[GateResult] = []
        failed_required: list[str] = []

        for name, check, required in self._gates:
            try:
                result = check()
            except Exception as exc:
                if self._fail_closed and required:
                    result = GateResult(
                        name=name,
                        status=GateStatus.FAIL,
                        reason=f"Gate execution failed (fail-closed): {exc}",
                    )
                else:
                    result = GateResult(
                        name=name,
                        status=GateStatus.SKIP,
                        reason=f"Gate execution error: {exc}",
                    )
            results.append(result)
            if result.status == GateStatus.FAIL and required:
                failed_required.append(name)

        passed = sum(1 for r in results if r.status == GateStatus.PASS)
        failed = sum(1 for r in results if r.status == GateStatus.FAIL)
        skipped = sum(1 for r in results if r.status == GateStatus.SKIP)

        return GateRunnerResult(
            all_pass=len(failed_required) == 0,
            total=len(results),
            passed=passed,
            failed=failed,
            skipped=skipped,
            failed_gate_names=tuple(failed_required),
            gates=tuple(results),
            verdict="ACCEPT" if len(failed_required) == 0 else "REJECT",
        )


def make_gate(
    name: str,
    condition: bool,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> GateResult:
    """Convenience: create a PASS/FAIL GateResult from a boolean condition."""
    return GateResult(
        name=name,
        status=GateStatus.PASS if condition else GateStatus.FAIL,
        reason=reason,
        evidence=evidence or {},
    )
