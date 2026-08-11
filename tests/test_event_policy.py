"""Tests for event policy classifier — fail-closed event stream evaluation."""

import json

import pytest

from agent_governance.event_policy import (
    EventClass,
    EventPolicyViolation,
    EventPolicyResult,
    classify_tool_name,
    classify_non_tool_event,
    evaluate_event_stream,
    extract_paths_from_event,
    normalize_event,
)
from agent_governance.task_spec import build_task_spec

VALID_SPEC = {
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


def _read_event(path: str) -> dict:
    return {
        "type": "assistant",
        "parent_tool_use_id": None,
        "message": {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Read", "id": "call_1", "input": {"file_path": path}},
            ],
        },
    }


def _write_event(path: str) -> dict:
    return {
        "type": "assistant",
        "parent_tool_use_id": None,
        "message": {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Write", "id": "call_1", "input": {"file_path": path, "content": "x"}},
            ],
        },
    }


def _edit_event(path: str) -> dict:
    return {
        "type": "assistant",
        "parent_tool_use_id": None,
        "message": {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Edit", "id": "call_1", "input": {"file_path": path, "old_string": "a", "new_string": "b"}},
            ],
        },
    }


def _glob_event(pattern: str) -> dict:
    return {
        "type": "assistant",
        "parent_tool_use_id": None,
        "message": {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Glob", "id": "call_1", "input": {"pattern": pattern}},
            ],
        },
    }


def _grep_event(pattern: str, path: str) -> dict:
    return {
        "type": "assistant",
        "parent_tool_use_id": None,
        "message": {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Grep", "id": "call_1", "input": {"pattern": pattern, "path": path}},
            ],
        },
    }


class TestToolClassification:
    """Tests for tool name → EventClass classification."""

    def test_read_tool(self):
        assert classify_tool_name("Read") == EventClass.FILESYSTEM_READ
        assert classify_tool_name("Glob") == EventClass.FILESYSTEM_READ
        assert classify_tool_name("Grep") == EventClass.FILESYSTEM_READ

    def test_write_tool(self):
        assert classify_tool_name("Write") == EventClass.FILESYSTEM_WRITE
        assert classify_tool_name("Edit") == EventClass.FILESYSTEM_WRITE
        assert classify_tool_name("NotebookEdit") == EventClass.FILESYSTEM_WRITE

    def test_shell_tool(self):
        assert classify_tool_name("Bash") == EventClass.SHELL
        assert classify_tool_name("PowerShell") == EventClass.SHELL

    def test_network_tool(self):
        assert classify_tool_name("WebSearch") == EventClass.NETWORK
        assert classify_tool_name("WebFetch") == EventClass.NETWORK

    def test_structured_output(self):
        assert classify_tool_name("StructuredOutput") == EventClass.STRUCTURED_RESULT_TRANSPORT

    def test_unknown_tool(self):
        assert classify_tool_name("SomeUnknownTool") == EventClass.UNKNOWN

    def test_non_tool_model_text(self):
        event = {"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}}
        assert classify_non_tool_event(event) == EventClass.MODEL_TEXT

    def test_non_tool_protocol(self):
        event = {"type": "result"}
        assert classify_non_tool_event(event) == EventClass.PROTOCOL_EVENT


class TestEventNormalization:
    """Tests for event normalization."""

    def test_normalize_read_event(self):
        norm = normalize_event(_read_event("src/calculator.py"))
        assert norm.action_class == EventClass.FILESYSTEM_READ
        assert "src/calculator.py" in norm.paths

    def test_normalize_unknown_tool(self):
        event = _read_event("src/file.py")
        event["message"]["content"][0]["name"] = "UnknownTool"
        norm = normalize_event(event)
        assert norm.action_class == EventClass.UNKNOWN

    def test_pathless_action(self):
        event = {
            "type": "assistant",
            "message": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "Read", "id": "call_1", "input": {}}],
            },
        }
        norm = normalize_event(event)
        assert norm.action_class == EventClass.FILESYSTEM_READ
        assert norm.paths == ()


class TestEventStreamEvaluation:
    """Tests for event stream evaluation with fail-closed behavior."""

    def test_valid_read_stream(self, tmp_path):
        task = build_task_spec(VALID_SPEC)
        events = [_read_event("src/calculator.py"), _read_event("tests/test.py")]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert result.valid
        assert result.filesystem_read_count == 2

    def test_out_of_scope_read_fails(self, tmp_path):
        """Regression: out-of-scope reads must be rejected."""
        task = build_task_spec(VALID_SPEC)
        events = [_read_event("other/secret.py")]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert not result.valid
        assert any(v.code == "OUT_OF_SCOPE" for v in result.violations)

    def test_out_of_scope_write_fails(self, tmp_path):
        """Regression: out-of-scope writes must be rejected."""
        task = build_task_spec(VALID_SPEC)
        events = [_write_event("other/file.py")]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert not result.valid
        assert any(v.code == "OUT_OF_SCOPE" for v in result.violations)

    def test_pathless_filesystem_action_fails(self, tmp_path):
        """Regression: pathless filesystem actions must fail closed."""
        task = build_task_spec(VALID_SPEC)
        events = [{
            "type": "assistant",
            "message": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Write", "id": "call_1", "input": {}}
                ],
            },
        }]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert not result.valid
        assert any(v.code == "PATHLESS_FILESYSTEM_ACTION" for v in result.violations)

    def test_unknown_tool_fails(self, tmp_path):
        """Regression: unknown tools must fail closed."""
        task = build_task_spec(VALID_SPEC)
        events = [{
            "type": "assistant",
            "message": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "MysteryTool", "id": "call_1", "input": {}}
                ],
            },
        }]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert not result.valid
        assert any(v.code == "UNKNOWN_TOOL" for v in result.violations)

    def test_shell_tool_rejected(self, tmp_path):
        task = build_task_spec(VALID_SPEC)
        events = [{
            "type": "assistant",
            "message": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Bash", "id": "call_1", "input": {"command": "ls"}}
                ],
            },
        }]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert not result.valid
        assert any(v.code == "FORBIDDEN_TOOL_CLASS" for v in result.violations)

    def test_glob_event_classified_as_read(self, tmp_path):
        task = build_task_spec(VALID_SPEC)
        events = [_glob_event("src/**/*.py")]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert result.filesystem_read_count == 1

    def test_pathless_glob_fails(self, tmp_path):
        """Regression: pathless Glob must fail closed."""
        task = build_task_spec(VALID_SPEC)
        events = [{
            "type": "assistant",
            "message": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "Glob", "id": "call_1", "input": {}}
                ],
            },
        }]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert not result.valid

    def test_structured_result_transport(self, tmp_path):
        """StructuredOutput must be explicitly categorized, not treated as arbitrary tool."""
        task = build_task_spec(VALID_SPEC)
        call_id = "call_struct_001"
        events = [
            {
                "type": "assistant",
                "message": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "name": "StructuredOutput", "id": call_id, "input": {"summary": "done"}}
                    ],
                },
            },
        ]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert result.structured_result_transport_count == 1

    def test_multi_path_action_validates_all(self, tmp_path):
        """Multi-path actions must validate ALL paths."""
        task = build_task_spec(VALID_SPEC)
        # Edit has file_path (in scope) but we test that a read of out-of-scope path fails
        events = [_read_event("other/secret.py"), _read_event("src/calculator.py")]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert not result.valid  # first event is out of scope

    def test_edit_event(self, tmp_path):
        task = build_task_spec(VALID_SPEC)
        events = [_edit_event("src/calculator.py")]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert result.valid
        assert result.filesystem_write_count == 1

    def test_edit_outside_scope_fails(self, tmp_path):
        task = build_task_spec(VALID_SPEC)
        events = [_edit_event("other/file.py")]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert not result.valid

    def test_grep_event(self, tmp_path):
        task = build_task_spec(VALID_SPEC)
        events = [_grep_event("def test", "src/")]
        result = evaluate_event_stream(events, task, workspace_root=str(tmp_path))
        assert result.filesystem_read_count == 1
