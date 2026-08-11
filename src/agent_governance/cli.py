"""Command-line interface for Agent Governance Kit.

Exit codes:
  0 — PASS (validation/check passed)
  1 — VALIDATION_FAILURE (input invalid)
  2 — POLICY_VIOLATION (policy rules violated)
  3 — INTEGRITY_FAILURE (repository integrity failed)
  4 — INTERNAL_ERROR (unexpected error)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .contracts import ContractValidationError, load_schema, validate_json_contract
from .event_policy import evaluate_event_stream, normalize_event
from .evidence import EvidenceBundle
from .gate_runner import GateRunner
from .patch_validator import validate_patch
from .policy import StaticPolicy
from .repo_guard import RepositoryGuardError, capture_snapshot, compare_snapshots
from .state_machine import (
    TERMINAL_STATES,
    AgentControlState,
    TransitionActor,
    assert_transition,
    transition_table,
)
from .task_spec import (
    TaskSpecValidationError,
    build_task_spec,
    validate_task_spec_structure,
)

EXIT_PASS = 0
EXIT_VALIDATION_FAILURE = 1
EXIT_POLICY_VIOLATION = 2
EXIT_INTEGRITY_FAILURE = 3
EXIT_INTERNAL_ERROR = 4


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _print_obj(obj: dict[str, Any]) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# ── subcommands ──────────────────────────────────────────────


def _validate_task(args: argparse.Namespace) -> int:
    """Validate a TaskSpec JSON file."""
    spec = _load_json(args.path)

    # Structural validation
    scopes, errors = validate_task_spec_structure(spec)
    if errors:
        _print_obj({"status": "VALIDATION_FAILURE", "errors": errors})
        return EXIT_VALIDATION_FAILURE

    if args.policy:
        policy_path = args.policy_config or None
        if policy_path:
            policy = StaticPolicy.load(policy_path)
        else:
            policy = StaticPolicy.from_dict({})
        result = policy.validate_task_spec(spec)
        if not result.valid:
            _print_obj({
                "status": "POLICY_VIOLATION",
                "violations": [v.to_dict() for v in result.violations],
            })
            return EXIT_POLICY_VIOLATION

    task_spec = build_task_spec(spec)
    _print_obj({
        "status": "OK",
        "task_id": task_spec.task_id,
        "task_type": task_spec.task_type,
        "task_spec_version": 2,
        "read_paths": list(task_spec.read_paths),
        "write_paths": list(task_spec.write_paths),
        "immutable_read_paths": list(task_spec.immutable_read_paths),
        "forbidden_paths": list(task_spec.forbidden_paths),
        "content_hash": task_spec.content_hash,
    })
    return EXIT_PASS


def _validate_policy(args: argparse.Namespace) -> int:
    """Validate a TaskSpec against a policy file."""
    spec = _load_json(args.task)
    policy = StaticPolicy.load(args.policy)
    result = policy.validate_task_spec(spec)
    _print_obj(result.to_dict())
    return EXIT_PASS if result.valid else EXIT_POLICY_VIOLATION


def _validate_events(args: argparse.Namespace) -> int:
    """Validate an event stream against a TaskSpec."""
    spec = _load_json(args.task)
    events = _load_json(args.events)
    try:
        task_spec = build_task_spec(spec)
    except TaskSpecValidationError as exc:
        _print_obj({"status": "VALIDATION_FAILURE", "error": str(exc)})
        return EXIT_VALIDATION_FAILURE

    result = evaluate_event_stream(
        events, task_spec, workspace_root=args.workspace or "."
    )
    _print_obj({
        "valid": result.valid,
        "violations": [
            {
                "event_id": v.event_id,
                "code": v.code,
                "message": v.message,
                "tool_name": v.tool_name,
                "paths": list(v.paths),
            }
            for v in result.violations
        ],
        "event_count": result.event_count,
        "structured_result_transport_count": result.structured_result_transport_count,
        "filesystem_read_count": result.filesystem_read_count,
        "filesystem_write_count": result.filesystem_write_count,
        "unknown_count": result.unknown_count,
    })
    return EXIT_PASS if result.valid else EXIT_POLICY_VIOLATION


def _validate_patch(args: argparse.Namespace) -> int:
    """Validate a patch file against a TaskSpec."""
    spec = _load_json(args.task)
    patch_text = Path(args.patch).read_text(encoding="utf-8")
    try:
        task_spec = build_task_spec(spec)
    except TaskSpecValidationError as exc:
        _print_obj({"status": "VALIDATION_FAILURE", "error": str(exc)})
        return EXIT_VALIDATION_FAILURE

    expected = tuple(args.expected) if args.expected else None
    result = validate_patch(
        patch_text,
        task_spec,
        expected_files=expected,
        repo_root=args.repo_root,
    )
    _print_obj(result.to_dict())
    return EXIT_PASS if result.valid else EXIT_VALIDATION_FAILURE


def _snapshot_repo(args: argparse.Namespace) -> int:
    """Capture a repository integrity snapshot."""
    try:
        snapshot = capture_snapshot(args.repo, protected_paths=args.protected)
        _print_obj(snapshot.to_dict())
        return EXIT_PASS
    except RepositoryGuardError as exc:
        _print_obj({"status": "INTEGRITY_FAILURE", "error": str(exc)})
        return EXIT_INTEGRITY_FAILURE


def _compare_repo(args: argparse.Namespace) -> int:
    """Compare two repository snapshots."""
    before = _load_json(args.before)
    after = _load_json(args.after)

    from .repo_guard import RepositorySnapshot

    before_snap = RepositorySnapshot(
        branch=before["branch"],
        head=before["head"],
        tracked_files=tuple(before["tracked_files"]),
        untracked_files=tuple(before["untracked_files"]),
        ignored_files=tuple(before.get("ignored_files", [])),
        protected_hashes=before.get("protected_hashes", {}),
        git_status_raw=before.get("git_status_raw", ""),
    )
    after_snap = RepositorySnapshot(
        branch=after["branch"],
        head=after["head"],
        tracked_files=tuple(after["tracked_files"]),
        untracked_files=tuple(after["untracked_files"]),
        ignored_files=tuple(after.get("ignored_files", [])),
        protected_hashes=after.get("protected_hashes", {}),
        git_status_raw=after.get("git_status_raw", ""),
    )

    volatile = frozenset(args.volatile) if args.volatile else None
    result = compare_snapshots(before_snap, after_snap, volatile_paths=volatile)
    _print_obj(result.to_dict())
    return EXIT_PASS if result.passed else EXIT_INTEGRITY_FAILURE


def _verify_evidence(args: argparse.Namespace) -> int:
    """Verify evidence manifest integrity."""
    bundle = EvidenceBundle(args.manifest_dir, must_be_empty=False)
    result = bundle.verify_manifest()
    _print_obj(result)
    return EXIT_PASS if result["valid"] else EXIT_INTEGRITY_FAILURE


def _list_transitions(_: argparse.Namespace) -> int:
    """Print the deterministic state transition table."""
    rows = []
    for t in transition_table():
        rows.append({
            "from": t.from_state.value,
            "to": t.to_state.value,
            "actor": t.actor.value,
            "reason": t.reason,
        })
    _print_obj({
        "status": "OK",
        "transitions": rows,
        "terminal_states": [s.value for s in TERMINAL_STATES],
    })
    return EXIT_PASS


def _check_transition(args: argparse.Namespace) -> int:
    """Check if a state transition is valid."""
    try:
        from_state = AgentControlState(args.from_state)
        to_state = AgentControlState(args.to_state)
        actor = TransitionActor(args.actor)
    except ValueError as exc:
        _print_obj({"status": "VALIDATION_FAILURE", "error": str(exc)})
        return EXIT_VALIDATION_FAILURE

    try:
        assert_transition(from_state, to_state, actor)
        _print_obj({
            "status": "OK",
            "valid": True,
            "from": from_state.value,
            "to": to_state.value,
            "actor": actor.value,
        })
        return EXIT_PASS
    except ValueError as exc:
        _print_obj({
            "status": "POLICY_VIOLATION",
            "valid": False,
            "error": str(exc),
        })
        return EXIT_POLICY_VIOLATION


# ── parser ───────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Agent Governance Kit — deterministic fail-closed agent governance"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate-task
    p = subparsers.add_parser("validate-task", help="Validate a TaskSpec JSON file")
    p.add_argument("path", type=Path, help="Path to TaskSpec JSON")
    p.add_argument("--policy", action="store_true", help="Also apply policy checks")
    p.add_argument("--policy-config", type=Path, help="Path to policy config JSON")
    p.set_defaults(func=_validate_task)

    # validate-policy
    p = subparsers.add_parser("validate-policy", help="Validate a TaskSpec against a policy")
    p.add_argument("--task", type=Path, required=True, help="Path to TaskSpec JSON")
    p.add_argument("--policy", type=Path, required=True, help="Path to policy JSON")
    p.set_defaults(func=_validate_policy)

    # validate-events
    p = subparsers.add_parser("validate-events", help="Validate an event stream against a TaskSpec")
    p.add_argument("--task", type=Path, required=True, help="Path to TaskSpec JSON")
    p.add_argument("--events", type=Path, required=True, help="Path to events JSON array")
    p.add_argument("--workspace", type=Path, help="Workspace root for path resolution")
    p.set_defaults(func=_validate_events)

    # validate-patch
    p = subparsers.add_parser("validate-patch", help="Validate a patch file against a TaskSpec")
    p.add_argument("--task", type=Path, required=True, help="Path to TaskSpec JSON")
    p.add_argument("--patch", type=Path, required=True, help="Path to patch file")
    p.add_argument("--expected", action="append", help="Expected changed file (repeatable)")
    p.add_argument("--repo-root", type=Path, help="Repository root for apply-check")
    p.set_defaults(func=_validate_patch)

    # snapshot-repo
    p = subparsers.add_parser("snapshot-repo", help="Capture a repository integrity snapshot")
    p.add_argument("--repo", type=Path, required=True, help="Repository root")
    p.add_argument("--protected", action="append", help="Protected file path (repeatable)")
    p.set_defaults(func=_snapshot_repo)

    # compare-repo
    p = subparsers.add_parser("compare-repo", help="Compare two repository snapshots")
    p.add_argument("--before", type=Path, required=True, help="Before snapshot JSON")
    p.add_argument("--after", type=Path, required=True, help="After snapshot JSON")
    p.add_argument("--volatile", action="append", help="Volatile path (repeatable)")
    p.set_defaults(func=_compare_repo)

    # verify-evidence
    p = subparsers.add_parser("verify-evidence", help="Verify evidence manifest integrity")
    p.add_argument("manifest_dir", type=Path, help="Evidence directory containing manifest")
    p.set_defaults(func=_verify_evidence)

    # list-transitions
    p = subparsers.add_parser("list-transitions", help="Print the deterministic state table")
    p.set_defaults(func=_list_transitions)

    # check-transition
    p = subparsers.add_parser("check-transition", help="Check if a state transition is valid")
    p.add_argument("--from-state", type=str, required=True, dest="from_state")
    p.add_argument("--to-state", type=str, required=True, dest="to_state")
    p.add_argument("--actor", type=str, required=True)
    p.set_defaults(func=_check_transition)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func: Callable[[argparse.Namespace], int] = args.func

    if hasattr(args, "json") and args.json:
        _print_obj({"error": "--json flag not yet implemented; default output is JSON"})
        return EXIT_INTERNAL_ERROR

    try:
        return func(args)
    except (ContractValidationError, TaskSpecValidationError, json.JSONDecodeError, OSError) as exc:
        _print_obj({"status": "ERROR", "error": str(exc)})
        return EXIT_VALIDATION_FAILURE
    except Exception as exc:
        _print_obj({"status": "INTERNAL_ERROR", "error": str(exc)})
        return EXIT_INTERNAL_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
