"""Deterministic patch validator — verifies patch paths, scope, identity, and apply-check."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .runtime_utils import sha256_file, sha256_text
from .task_spec import TaskSpec, normalize_repo_path


class PatchValidationError(ValueError):
    """Raised when patch validation fails on a structural or scope issue."""


@dataclass(frozen=True)
class ParsedPatchFile:
    """A single file entry parsed from a unified diff or git diff."""

    old_path: str
    new_path: str
    is_new: bool
    is_deleted: bool
    is_rename: bool
    is_binary: bool
    file_mode: str | None = None


@dataclass(frozen=True)
class PatchValidationResult:
    """Result of patch validation."""

    valid: bool
    errors: tuple[str, ...]
    files_changed: tuple[ParsedPatchFile, ...]
    repo_relative: bool
    scope_valid: bool
    scope_exact: bool
    content_hashes: dict[str, str] = field(default_factory=dict)
    apply_check_passed: bool | None = None  # None if git not available

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "files_changed": [
                {
                    "old_path": f.old_path,
                    "new_path": f.new_path,
                    "is_new": f.is_new,
                    "is_deleted": f.is_deleted,
                    "is_rename": f.is_rename,
                    "is_binary": f.is_binary,
                }
                for f in self.files_changed
            ],
            "repo_relative": self.repo_relative,
            "scope_valid": self.scope_valid,
            "scope_exact": self.scope_exact,
            "apply_check_passed": self.apply_check_passed,
        }


# Git diff header patterns
_GIT_DIFF_HEADER = re.compile(
    r"^diff --git a/(.+) b/(.+)$"
)
_GIT_OLD_MODE = re.compile(r"^old mode (\d+)$")
_GIT_NEW_MODE = re.compile(r"^new mode (\d+)$")
_GIT_NEW_FILE = re.compile(r"^new file mode (\d+)$")
_GIT_DELETED_FILE = re.compile(r"^deleted file mode (\d+)$")
_GIT_RENAME = re.compile(r"^rename (?:from|to) (.+)$")
_GIT_BINARY = re.compile(r"^Binary files .+ differ$")
_GIT_INDEX_LINE = re.compile(r"^index ([0-9a-f]+)\.\.([0-9a-f]+)(?: (\d+))?$")
_GIT_SIMILARITY = re.compile(r"^similarity index \d+%$")
_GIT_DISSIMILARITY = re.compile(r"^dissimilarity index \d+%$")


def parse_patch(patch_text: str) -> list[ParsedPatchFile]:
    """Parse a git-format patch into structured file entries."""
    files: list[ParsedPatchFile] = []
    lines = patch_text.splitlines()
    current: dict[str, Any] | None = None

    for line in lines:
        header_match = _GIT_DIFF_HEADER.match(line)
        if header_match:
            if current is not None:
                files.append(_finalize_parsed(current))
            current = {
                "old_path": header_match.group(1),
                "new_path": header_match.group(2),
                "is_new": False,
                "is_deleted": False,
                "is_rename": False,
                "is_binary": False,
                "file_mode": None,
            }
            # Detect rename
            if current["old_path"] != current["new_path"]:
                current["is_rename"] = True
            continue

        if current is None:
            continue

        if _GIT_NEW_FILE.match(line):
            current["is_new"] = True
            current["file_mode"] = _GIT_NEW_FILE.match(line).group(1)
        elif _GIT_DELETED_FILE.match(line):
            current["is_deleted"] = True
        elif _GIT_RENAME.match(line):
            current["is_rename"] = True
        elif _GIT_BINARY.match(line):
            current["is_binary"] = True

    if current is not None:
        files.append(_finalize_parsed(current))

    return files


def _finalize_parsed(raw: dict[str, Any]) -> ParsedPatchFile:
    return ParsedPatchFile(
        old_path=raw["old_path"],
        new_path=raw["new_path"],
        is_new=raw["is_new"],
        is_deleted=raw["is_deleted"],
        is_rename=raw["is_rename"],
        is_binary=raw["is_binary"],
        file_mode=raw.get("file_mode"),
    )


def validate_patch(
    patch_text: str,
    task_spec: TaskSpec,
    *,
    expected_files: tuple[str, ...] | None = None,
    repo_root: str | Path | None = None,
    require_apply_check: bool = False,
) -> PatchValidationResult:
    """Validate a patch against a TaskSpec's write scope.

    Checks:
    - All paths are repository-relative
    - No absolute paths or traversal
    - Changed files are within write scope
    - Optional scope_exact (if expected_files provided)
    - Content hashing
    - Optional git apply --check
    """
    errors: list[str] = []
    files = parse_patch(patch_text)

    if not files:
        errors.append("Patch contains no parseable file changes")
        return PatchValidationResult(
            valid=False,
            errors=tuple(errors),
            files_changed=(),
            repo_relative=False,
            scope_valid=False,
            scope_exact=False,
        )

    # Check repo-relative paths
    repo_relative = True
    for f in files:
        for path in (f.old_path, f.new_path):
            if not path or path == "/dev/null":
                continue
            try:
                normalize_repo_path(path)
            except ValueError as exc:
                errors.append(f"Path {path!r} in patch is not repo-relative: {exc}")
                repo_relative = False

    # Check write scope
    scope_valid = True
    changed_files = set()
    for f in files:
        if f.is_deleted:
            path = f.old_path
        else:
            path = f.new_path
        if not path or path == "/dev/null":
            continue
        changed_files.add(path)

        try:
            norm = normalize_repo_path(path)
        except ValueError:
            scope_valid = False
            continue

        allowed, reason = task_spec.validate_path_access(norm, "write")
        if not allowed:
            errors.append(f"File {norm!r} is not in write scope: {reason}")
            scope_valid = False

    # Scope exact check
    scope_exact = True
    if expected_files is not None:
        expected_set = {normalize_repo_path(p) for p in expected_files}
        changed_set = set()
        for f in files:
            path = f.new_path if not f.is_deleted else f.old_path
            if path and path != "/dev/null":
                try:
                    changed_set.add(normalize_repo_path(path))
                except ValueError:
                    pass
        if changed_set != expected_set:
            extra = changed_set - expected_set
            missing = expected_set - changed_set
            if extra:
                errors.append(f"Unexpected files in patch: {sorted(extra)}")
            if missing:
                errors.append(f"Expected files missing from patch: {sorted(missing)}")
            scope_exact = False

    # Content hashing
    content_hashes: dict[str, str] = {}
    if repo_root is not None:
        root = Path(repo_root)
        for f in files:
            path = f.new_path if not f.is_deleted else f.old_path
            if not path or path == "/dev/null":
                continue
            file_path = root / path
            if file_path.is_file():
                content_hashes[path] = sha256_file(file_path)

    # Apply-check
    apply_check_passed: bool | None = None
    if repo_root is not None:
        try:
            result = subprocess.run(
                ["git", "apply", "--check"],
                input=patch_text,
                capture_output=True,
                text=True,
                cwd=str(repo_root),
                timeout=30,
            )
            apply_check_passed = result.returncode == 0
            if not apply_check_passed:
                errors.append(f"git apply --check failed: {result.stderr.strip()}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            if require_apply_check:
                errors.append("git apply --check required but git is unavailable")
            apply_check_passed = None

    return PatchValidationResult(
        valid=len(errors) == 0,
        errors=tuple(errors),
        files_changed=tuple(files),
        repo_relative=repo_relative,
        scope_valid=scope_valid,
        scope_exact=scope_exact,
        content_hashes=content_hashes,
        apply_check_passed=apply_check_passed,
    )
