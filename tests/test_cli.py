"""Tests for CLI interface — exit codes and subcommand behavior."""

import json
from pathlib import Path

import pytest

from agent_governance.cli import (
    EXIT_PASS,
    EXIT_VALIDATION_FAILURE,
    EXIT_POLICY_VIOLATION,
    EXIT_INTEGRITY_FAILURE,
    EXIT_INTERNAL_ERROR,
    main,
)

VALID_TASK_SPEC = {
    "task_spec_version": 2,
    "task_id": "test-001",
    "task_type": "bug_fix",
    "base_commit": "a" * 40,
    "read_paths": ["src/", "tests/"],
    "write_paths": ["src/calculator.py"],
    "immutable_read_paths": [],
    "forbidden_paths": [],
    "max_execution_minutes": 30,
    "max_agent_turns": 50,
    "max_rework_cycles": 3,
    "execution_mode": "sequential",
}


class TestCLIExitCodes:
    """Tests for CLI exit codes."""

    def test_validate_task_pass(self, tmp_path):
        spec_path = tmp_path / "task.json"
        spec_path.write_text(json.dumps(VALID_TASK_SPEC))
        exit_code = main(["validate-task", str(spec_path)])
        assert exit_code == EXIT_PASS

    def test_validate_task_failure(self, tmp_path):
        spec_path = tmp_path / "bad.json"
        spec_path.write_text(json.dumps({"task_id": "incomplete"}))
        exit_code = main(["validate-task", str(spec_path)])
        assert exit_code == EXIT_VALIDATION_FAILURE

    def test_validate_task_with_policy_pass(self, tmp_path):
        spec_path = tmp_path / "task.json"
        spec_path.write_text(json.dumps(VALID_TASK_SPEC))
        exit_code = main(["validate-task", str(spec_path), "--policy"])
        assert exit_code == EXIT_PASS

    def test_validate_task_with_policy_violation(self, tmp_path):
        spec_path = tmp_path / "task.json"
        bad_spec = {**VALID_TASK_SPEC, "execution_mode": "parallel"}
        spec_path.write_text(json.dumps(bad_spec))
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(json.dumps({
            "required_task_modes": {"execution_mode": "sequential"},
            "limits": {},
        }))
        exit_code = main([
            "validate-task", str(spec_path), "--policy",
            "--policy-config", str(policy_path),
        ])
        assert exit_code == EXIT_POLICY_VIOLATION

    def test_validate_policy(self, tmp_path):
        task_path = tmp_path / "task.json"
        task_path.write_text(json.dumps(VALID_TASK_SPEC))
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(json.dumps({"limits": {}, "required_task_modes": {}}))
        exit_code = main([
            "validate-policy", "--task", str(task_path), "--policy", str(policy_path),
        ])
        assert exit_code == EXIT_PASS

    def test_list_transitions(self):
        exit_code = main(["list-transitions"])
        assert exit_code == EXIT_PASS

    def test_check_transition_valid(self):
        exit_code = main([
            "check-transition",
            "--from-state", "NEW",
            "--to-state", "PLANNING",
            "--actor", "ORCHESTRATOR",
        ])
        assert exit_code == EXIT_PASS

    def test_check_transition_invalid(self):
        exit_code = main([
            "check-transition",
            "--from-state", "NEW",
            "--to-state", "ACCEPTED",
            "--actor", "ORCHESTRATOR",
        ])
        assert exit_code == EXIT_POLICY_VIOLATION

    def test_check_transition_terminal(self):
        exit_code = main([
            "check-transition",
            "--from-state", "ACCEPTED",
            "--to-state", "NEW",
            "--actor", "ORCHESTRATOR",
        ])
        assert exit_code == EXIT_POLICY_VIOLATION

    def test_validate_events(self, tmp_path):
        task_path = tmp_path / "task.json"
        task_path.write_text(json.dumps(VALID_TASK_SPEC))
        events_path = tmp_path / "events.json"
        events_path.write_text(json.dumps([{
            "type": "assistant",
            "message": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Read", "id": "c1", "input": {"file_path": "src/calculator.py"}},
                ],
            },
        }]))
        exit_code = main([
            "validate-events",
            "--task", str(task_path),
            "--events", str(events_path),
            "--workspace", str(tmp_path),
        ])
        assert exit_code == EXIT_PASS

    def test_validate_events_policy_violation(self, tmp_path):
        task_path = tmp_path / "task.json"
        task_path.write_text(json.dumps(VALID_TASK_SPEC))
        events_path = tmp_path / "events.json"
        events_path.write_text(json.dumps([{
            "type": "assistant",
            "message": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash", "id": "c1", "input": {"command": "rm -rf /"}},
                ],
            },
        }]))
        exit_code = main([
            "validate-events",
            "--task", str(task_path),
            "--events", str(events_path),
            "--workspace", str(tmp_path),
        ])
        assert exit_code == EXIT_POLICY_VIOLATION

    def test_validate_patch(self, tmp_path):
        task_path = tmp_path / "task.json"
        task_path.write_text(json.dumps(VALID_TASK_SPEC))
        patch_path = tmp_path / "patch.diff"
        patch_path.write_text("""diff --git a/src/calculator.py b/src/calculator.py
index abc..def 100644
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1 +1 @@
-old
+new
""")
        exit_code = main([
            "validate-patch",
            "--task", str(task_path),
            "--patch", str(patch_path),
        ])
        assert exit_code == EXIT_PASS

    def test_validate_patch_out_of_scope(self, tmp_path):
        task_path = tmp_path / "task.json"
        task_path.write_text(json.dumps(VALID_TASK_SPEC))
        patch_path = tmp_path / "patch.diff"
        patch_path.write_text("""diff --git a/secret/file.py b/secret/file.py
index abc..def 100644
--- a/secret/file.py
+++ b/secret/file.py
@@ -1 +1 @@
-old
+new
""")
        exit_code = main([
            "validate-patch",
            "--task", str(task_path),
            "--patch", str(patch_path),
        ])
        assert exit_code == EXIT_VALIDATION_FAILURE

    def test_verify_evidence(self, tmp_path):
        from agent_governance.evidence import EvidenceBundle
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.write_json("report.json", {"status": "PASS"})
        bundle.build_manifest()
        exit_code = main(["verify-evidence", str(tmp_path / "evidence")])
        assert exit_code == EXIT_PASS

    def test_verify_evidence_tampered(self, tmp_path):
        from agent_governance.evidence import EvidenceBundle
        bundle = EvidenceBundle(tmp_path / "evidence")
        bundle.write_json("report.json", {"status": "PASS"})
        bundle.build_manifest()
        # Tamper
        bundle.write_json("report.json", {"status": "TAMPERED"})
        exit_code = main(["verify-evidence", str(tmp_path / "evidence")])
        assert exit_code == EXIT_INTEGRITY_FAILURE

    def test_nonexistent_file(self):
        exit_code = main(["validate-task", "nonexistent_file.json"])
        assert exit_code == EXIT_VALIDATION_FAILURE
