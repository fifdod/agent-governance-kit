"""Tests for deterministic patch validator."""

import pytest

from agent_governance.patch_validator import (
    ParsedPatchFile,
    PatchValidationError,
    parse_patch,
    validate_patch,
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

SIMPLE_PATCH = """diff --git a/src/calculator.py b/src/calculator.py
index abc1234..def5678 100644
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,3 +1,3 @@
 def add(a, b):
-    return a - b
+    return a + b
"""

RENAME_PATCH = """diff --git a/src/old_name.py b/src/new_name.py
similarity index 95%
rename from src/old_name.py
rename to src/new_name.py
index abc1234..def5678 100644
--- a/src/old_name.py
+++ b/src/new_name.py
@@ -1,3 +1,3 @@
 def foo():
-    return 1
+    return 2
"""

DELETE_PATCH = """diff --git a/src/deprecated.py b/src/deprecated.py
deleted file mode 100644
index abc1234..0000000
--- a/src/deprecated.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def old_func():
-    pass
"""

NEW_FILE_PATCH = """diff --git a/src/new_module.py b/src/new_module.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/src/new_module.py
@@ -0,0 +1,3 @@
+def new_func():
+    pass
"""


class TestPatchParsing:
    """Tests for git patch parsing."""

    def test_parse_simple_patch(self):
        files = parse_patch(SIMPLE_PATCH)
        assert len(files) == 1
        assert files[0].old_path == "src/calculator.py"
        assert files[0].new_path == "src/calculator.py"
        assert not files[0].is_new
        assert not files[0].is_deleted
        assert not files[0].is_rename

    def test_parse_rename_patch(self):
        files = parse_patch(RENAME_PATCH)
        assert len(files) == 1
        assert files[0].is_rename
        assert files[0].old_path == "src/old_name.py"
        assert files[0].new_path == "src/new_name.py"

    def test_parse_delete_patch(self):
        files = parse_patch(DELETE_PATCH)
        assert len(files) == 1
        assert files[0].is_deleted
        assert files[0].old_path == "src/deprecated.py"

    def test_parse_new_file_patch(self):
        files = parse_patch(NEW_FILE_PATCH)
        assert len(files) == 1
        assert files[0].is_new
        assert files[0].new_path == "src/new_module.py"

    def test_empty_patch(self):
        files = parse_patch("")
        assert files == []

    def test_non_git_patch(self):
        files = parse_patch("random text\nnot a patch")
        assert files == []


class TestPatchValidation:
    """Tests for patch validation against TaskSpec."""

    def test_valid_patch_in_scope(self):
        task = build_task_spec(VALID_SPEC)
        result = validate_patch(SIMPLE_PATCH, task)
        assert result.valid
        assert result.scope_valid
        assert result.repo_relative

    def test_patch_outside_write_scope(self):
        """Patch validation must reject files outside write scope."""
        task = build_task_spec(VALID_SPEC)
        bad_patch = """diff --git a/other/secret.py b/other/secret.py
index abc1234..def5678 100644
--- a/other/secret.py
+++ b/other/secret.py
@@ -1 +1 @@
-x
+y
"""
        result = validate_patch(bad_patch, task)
        assert not result.valid
        assert not result.scope_valid

    def test_absolute_path_rejected(self):
        """Repository-relative paths are required."""
        task = build_task_spec(VALID_SPEC)
        bad_patch = """diff --git a//abs/path/src/calculator.py b//abs/path/src/calculator.py
index abc1234..def5678 100644
--- a//abs/path/src/calculator.py
+++ b//abs/path/src/calculator.py
@@ -1 +1 @@
-x
+y
"""
        result = validate_patch(bad_patch, task)
        assert not result.valid

    def test_scope_exact_enforcement(self):
        """scope_exact detects unexpected files in patch."""
        task = build_task_spec(VALID_SPEC)
        result = validate_patch(
            SIMPLE_PATCH, task, expected_files=("src/calculator.py",)
        )
        assert result.valid
        assert result.scope_exact

    def test_unexpected_file_detected(self):
        """Unexpected file in patch is detected."""
        task = build_task_spec(VALID_SPEC)
        result = validate_patch(
            SIMPLE_PATCH, task, expected_files=("src/other.py",)
        )
        assert not result.valid
        assert not result.scope_exact

    def test_traversal_rejected(self):
        task = build_task_spec(VALID_SPEC)
        bad_patch = """diff --git a/../escape/src/calculator.py b/../escape/src/calculator.py
index abc1234..def5678 100644
--- a/../escape/src/calculator.py
+++ b/../escape/src/calculator.py
@@ -1 +1 @@
-x
+y
"""
        result = validate_patch(bad_patch, task)
        assert not result.valid

    def test_patch_rename_parsing(self):
        """Git rename arrows must be parsed correctly."""
        task = build_task_spec({**VALID_SPEC, "write_paths": ["src/"]})
        result = validate_patch(RENAME_PATCH, task)
        assert len(result.files_changed) == 1
        assert result.files_changed[0].is_rename

    def test_patch_delete_detection(self):
        task = build_task_spec({**VALID_SPEC, "write_paths": ["src/deprecated.py"]})
        result = validate_patch(DELETE_PATCH, task)
        assert len(result.files_changed) == 1
        assert result.files_changed[0].is_deleted

    def test_patch_create_detection(self):
        task = build_task_spec({**VALID_SPEC, "write_paths": ["src/"]})
        result = validate_patch(NEW_FILE_PATCH, task)
        assert len(result.files_changed) == 1
        assert result.files_changed[0].is_new

    def test_multifile_patch(self):
        task = build_task_spec({**VALID_SPEC, "write_paths": ["src/"]})
        multifile = SIMPLE_PATCH + "\n" + NEW_FILE_PATCH
        result = validate_patch(multifile, task)
        assert len(result.files_changed) == 2

    def test_empty_patch_validates(self):
        task = build_task_spec(VALID_SPEC)
        result = validate_patch("", task)
        assert not result.valid  # empty patch produces no parseable files
