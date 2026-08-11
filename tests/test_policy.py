"""Tests for static policy engine."""

import json
from pathlib import Path

import pytest

from agent_governance.policy import (
    PolicyViolation,
    PolicyResult,
    StaticPolicy,
    _matches_path,
)
from agent_governance.task_spec import build_task_spec

VALID_SPEC = {
    "task_spec_version": 2,
    "task_id": "test-001",
    "task_type": "bug_fix",
    "base_commit": "a" * 40,
    "read_paths": ["src/", "tests/"],
    "write_paths": ["src/calculator.py"],
    "immutable_read_paths": ["tests/"],
    "forbidden_paths": [],
    "max_execution_minutes": 30,
    "max_agent_turns": 50,
    "max_rework_cycles": 3,
    "execution_mode": "sequential",
}

SAMPLE_POLICY = {
    "policy_version": "0.1.0",
    "global_forbidden_path_patterns": [".env", "**/secrets/**", "**/credentials*"],
    "global_forbidden_command_patterns": ["rm -rf", "DROP TABLE"],
    "limits": {"max_execution_minutes": 60, "max_agent_turns": 100},
    "required_task_modes": {"execution_mode": "sequential"},
}


class TestStaticPolicy:
    """Tests for the StaticPolicy class."""

    def test_load_from_dict(self):
        policy = StaticPolicy.from_dict(SAMPLE_POLICY)
        assert policy.content_hash

    def test_load_from_file(self, tmp_path):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(SAMPLE_POLICY))
        policy = StaticPolicy.load(path)
        assert policy.forbidden_path_patterns

    def test_stable_content_hash(self):
        a = StaticPolicy.from_dict(SAMPLE_POLICY)
        b = StaticPolicy.from_dict(SAMPLE_POLICY)
        assert a.content_hash == b.content_hash

    def test_validate_valid_task_spec(self):
        policy = StaticPolicy.from_dict(SAMPLE_POLICY)
        result = policy.validate_task_spec(VALID_SPEC)
        assert result.valid
        assert len(result.violations) == 0

    def test_limit_exceeded(self):
        policy = StaticPolicy.from_dict(SAMPLE_POLICY)
        spec = {**VALID_SPEC, "max_execution_minutes": 999}
        result = policy.validate_task_spec(spec)
        assert not result.valid
        assert any(v.code == "LIMIT_EXCEEDED" for v in result.violations)

    def test_mode_not_allowed(self):
        policy = StaticPolicy.from_dict(SAMPLE_POLICY)
        spec = {**VALID_SPEC, "execution_mode": "parallel"}
        result = policy.validate_task_spec(spec)
        assert not result.valid
        assert any(v.code == "MODE_NOT_ALLOWED" for v in result.violations)

    def test_forbidden_path_pattern(self):
        policy = StaticPolicy.from_dict(SAMPLE_POLICY)
        # "config/secrets/key.txt" should match "**/secrets/**" pattern
        spec = {
            **VALID_SPEC,
            "read_paths": ["config/secrets/key.txt", "src/"],
            "forbidden_paths": [],
            "immutable_read_paths": [],
        }
        result = policy.validate_task_spec(spec)
        assert not result.valid
        assert any(v.code == "FORBIDDEN_PATH" for v in result.violations)

    def test_forbidden_command_pattern(self):
        policy = StaticPolicy.from_dict(SAMPLE_POLICY)
        spec = {**VALID_SPEC, "allowed_commands": ["rm -rf /tmp"]}
        result = policy.validate_task_spec(spec)
        assert not result.valid
        assert any(v.code == "FORBIDDEN_COMMAND" for v in result.violations)

    def test_path_rule_conflict(self):
        policy = StaticPolicy.from_dict(SAMPLE_POLICY)
        # forbidden_paths always win — overlap between read and forbidden
        spec = {**VALID_SPEC, "forbidden_paths": ["src/calculator.py"]}
        # src/calculator.py is in write_paths, so forbidden overlaps write_paths
        result = policy.validate_task_spec(spec)
        assert not result.valid

    def test_invalid_task_spec_fails(self):
        policy = StaticPolicy.from_dict(SAMPLE_POLICY)
        result = policy.validate_task_spec({"task_id": "bad"})
        assert not result.valid
        assert any(v.code == "TASKSPEC_INVALID" for v in result.violations)

    def test_path_matching(self):
        assert _matches_path(".env", ".env")
        assert _matches_path("**/secrets/**", "config/secrets/key.txt")
        assert not _matches_path("*.pem", "key.txt")

    def test_policy_hash_matches(self):
        policy = StaticPolicy.from_dict(SAMPLE_POLICY)
        result = policy.validate_task_spec(VALID_SPEC)
        assert result.policy_hash == policy.content_hash
