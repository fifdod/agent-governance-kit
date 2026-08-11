"""Tests for TaskSpec v2 — four-category path semantics."""

import json

import pytest

from agent_governance.task_spec import (
    TASK_SPEC_VERSION,
    TaskSpec,
    TaskSpecValidationError,
    build_task_spec,
    normalize_repo_path,
    normalize_scope_list,
    scope_contains,
    scopes_overlap,
    validate_task_spec_structure,
)


VALID_SPEC = {
    "task_spec_version": 2,
    "task_id": "test-001",
    "task_type": "bug_fix",
    "base_commit": "a" * 40,
    "read_paths": ["src/", "tests/"],
    "write_paths": ["src/calculator.py"],
    "immutable_read_paths": ["tests/"],
    "forbidden_paths": ["config/secrets/"],
    "allowed_commands": ["python -m pytest"],
    "required_tests": ["python -m pytest tests/"],
    "max_execution_minutes": 30,
    "max_agent_turns": 50,
    "max_rework_cycles": 3,
    "execution_mode": "sequential",
}


class TestTaskSpecStructure:
    """Tests for TaskSpec v2 structure validation."""

    def test_valid_structure(self):
        scopes, errors = validate_task_spec_structure(VALID_SPEC)
        assert errors == []
        assert scopes["read_paths"] == ["src", "tests"]
        assert scopes["write_paths"] == ["src/calculator.py"]

    def test_missing_version(self):
        spec = {**VALID_SPEC, "task_spec_version": 1}
        _, errors = validate_task_spec_structure(spec)
        assert any("task_spec_version must equal 2" in e for e in errors)

    def test_rejects_legacy_allowed_paths(self):
        spec = {**VALID_SPEC, "allowed_paths": ["src/"]}
        _, errors = validate_task_spec_structure(spec)
        assert any("legacy allowed_paths" in e for e in errors)

    def test_read_paths_required(self):
        spec = {**VALID_SPEC, "read_paths": []}
        _, errors = validate_task_spec_structure(spec)
        assert any("read_paths must be a non-empty array" in e for e in errors)

    def test_write_paths_required(self):
        spec = {**VALID_SPEC, "write_paths": []}
        _, errors = validate_task_spec_structure(spec)
        assert any("write_paths must be a non-empty array" in e for e in errors)

    def test_write_paths_must_be_subset_of_read(self):
        spec = {**VALID_SPEC, "write_paths": ["other/"]}
        _, errors = validate_task_spec_structure(spec)
        assert any("write_paths is not a subset of read_paths" in e for e in errors)

    def test_immutable_must_be_subset_of_read(self):
        spec = {**VALID_SPEC, "immutable_read_paths": ["other/"]}
        _, errors = validate_task_spec_structure(spec)
        assert any("immutable_read_paths is not a subset of read_paths" in e for e in errors)

    def test_immutable_overlaps_write_rejected(self):
        spec = {**VALID_SPEC, "immutable_read_paths": ["src/calculator.py"]}
        _, errors = validate_task_spec_structure(spec)
        assert any("immutable_read_paths overlaps write_paths" in e for e in errors)

    def test_forbidden_overlaps_read_rejected(self):
        spec = {**VALID_SPEC, "forbidden_paths": ["src/"]}
        _, errors = validate_task_spec_structure(spec)
        assert any("forbidden_paths overlaps read_paths" in e for e in errors)

    def test_forbidden_overlaps_write_rejected(self):
        spec = {**VALID_SPEC, "forbidden_paths": ["src/calculator.py"]}
        _, errors = validate_task_spec_structure(spec)
        assert any("forbidden_paths overlaps write_paths" in e for e in errors)

    def test_nonexistent_field_not_array(self):
        spec = {**VALID_SPEC, "read_paths": "not_array"}
        _, errors = validate_task_spec_structure(spec)
        assert any("read_paths must be an array" in e for e in errors)

    def test_duplicate_paths_detected(self):
        spec = {**VALID_SPEC, "read_paths": ["src/", "src/"]}
        _, errors = validate_task_spec_structure(spec)
        assert any("duplicate" in e for e in errors)

    def test_absolute_path_rejected(self):
        spec = {**VALID_SPEC, "read_paths": ["/absolute/path"]}
        _, errors = validate_task_spec_structure(spec)
        assert any("appears absolute" in e for e in errors)

    def test_traversal_rejected(self):
        spec = {**VALID_SPEC, "read_paths": ["../escape"]}
        _, errors = validate_task_spec_structure(spec)
        assert any("traversal" in e for e in errors)


class TestTaskSpec:
    """Tests for the built TaskSpec object."""

    def test_build_valid(self):
        task = build_task_spec(VALID_SPEC)
        assert task.task_id == "test-001"
        assert task.task_type == "bug_fix"
        assert "src" in task.read_paths
        assert "src/calculator.py" in task.write_paths

    def test_content_hash_stable(self):
        a = build_task_spec(VALID_SPEC)
        b = build_task_spec(VALID_SPEC)
        assert a.content_hash == b.content_hash

    def test_content_hash_differs(self):
        a = build_task_spec(VALID_SPEC)
        b = build_task_spec({**VALID_SPEC, "task_id": "test-002"})
        assert a.content_hash != b.content_hash

    def test_is_path_readable(self):
        task = build_task_spec(VALID_SPEC)
        assert task.is_path_readable("src/calculator.py")
        assert task.is_path_readable("tests/test_calc.py")
        assert not task.is_path_readable("other/file.py")
        assert not task.is_path_readable("config/secrets/key.txt")

    def test_is_path_writable(self):
        task = build_task_spec(VALID_SPEC)
        assert task.is_path_writable("src/calculator.py")
        assert not task.is_path_writable("tests/test_calc.py")  # immutable
        assert not task.is_path_writable("other/file.py")
        assert not task.is_path_writable("config/secrets/key.txt")

    def test_validate_path_access_read(self):
        task = build_task_spec(VALID_SPEC)
        allowed, _ = task.validate_path_access("src/calculator.py", "read")
        assert allowed
        allowed, _ = task.validate_path_access("other/file.py", "read")
        assert not allowed

    def test_validate_path_access_write(self):
        task = build_task_spec(VALID_SPEC)
        allowed, _ = task.validate_path_access("src/calculator.py", "write")
        assert allowed
        allowed, _ = task.validate_path_access("tests/test_calc.py", "write")
        assert not allowed  # immutable

    def test_forbidden_paths_always_win(self):
        task = build_task_spec(VALID_SPEC)
        # Even though read_paths includes src/, if forbidden_paths wins at exact match
        allowed, _ = task.validate_path_access("config/secrets/key.txt", "read")
        assert not allowed

    def test_to_dict(self):
        task = build_task_spec(VALID_SPEC)
        d = task.to_dict()
        assert d["task_spec_version"] == 2
        assert d["task_id"] == "test-001"

    def test_empty_task_id_rejected(self):
        with pytest.raises(TaskSpecValidationError):
            build_task_spec({**VALID_SPEC, "task_id": ""})

    def test_bad_commit_rejected(self):
        with pytest.raises(TaskSpecValidationError):
            build_task_spec({**VALID_SPEC, "base_commit": "short"})

    def test_scope_contains(self):
        assert scope_contains("src", "src/calculator.py")
        assert scope_contains("src/calculator.py", "src/calculator.py")
        assert not scope_contains("src", "tests/test.py")

    def test_scopes_overlap(self):
        assert scopes_overlap("src", "src/calculator.py")
        assert scopes_overlap("src/calculator.py", "src")
        assert not scopes_overlap("src", "tests")

    def test_normalize_repo_path(self):
        assert normalize_repo_path("Src/Calculator.py") == "src/calculator.py"
        assert normalize_repo_path("./src/file.py") == "src/file.py"
        with pytest.raises(ValueError, match="absolute"):
            normalize_repo_path("/abs/path")
        with pytest.raises(ValueError, match="traversal"):
            normalize_repo_path("../escape")
        with pytest.raises(ValueError, match="non-empty"):
            normalize_repo_path("")

    def test_read_and_write_scope_independent(self):
        """Regression: read scope does not imply write scope."""
        spec = {
            **VALID_SPEC,
            "read_paths": ["src/", "docs/"],
            "write_paths": ["src/calculator.py"],
            "immutable_read_paths": [],
            "forbidden_paths": [],
        }
        task = build_task_spec(spec)
        # Readable but NOT writable
        assert task.is_path_readable("docs/readme.md")
        assert not task.is_path_writable("docs/readme.md")
