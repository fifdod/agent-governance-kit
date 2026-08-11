"""Repository guard — snapshot and integrity comparison.

Takes before/after snapshots of a repository and compares protected invariants.
CRITICAL: Volatile-path exemptions must distinguish between expected transient
artifacts and tracked/protected content. A volatile-path rule must never
automatically authorize modification of a tracked protected file.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .runtime_utils import sha256_file


class RepositoryGuardError(RuntimeError):
    """Raised when repository integrity check fails."""


@dataclass(frozen=True)
class RepositorySnapshot:
    """A point-in-time snapshot of repository state."""

    branch: str
    head: str
    tracked_files: tuple[str, ...]
    untracked_files: tuple[str, ...]
    ignored_files: tuple[str, ...]
    protected_hashes: dict[str, str]
    git_status_raw: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "head": self.head,
            "tracked_files": list(self.tracked_files),
            "untracked_files": list(self.untracked_files),
            "ignored_files": list(self.ignored_files),
            "protected_hashes": dict(self.protected_hashes),
            "git_status_raw": self.git_status_raw,
        }


@dataclass(frozen=True)
class RepositoryIntegrityResult:
    """Result of comparing two repository snapshots."""

    result: str  # "EXACT_MATCH", "VOLATILE_ONLY", "INTEGRITY_FAILURE"
    branch_unchanged: bool
    head_unchanged: bool
    protected_hashes_unchanged: bool
    tracked_state_unchanged: bool
    volatile_differences: tuple[dict[str, str], ...]
    unexpected_differences: tuple[dict[str, str], ...]
    errors: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.result in ("EXACT_MATCH", "VOLATILE_ONLY")

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "branch_unchanged": self.branch_unchanged,
            "head_unchanged": self.head_unchanged,
            "protected_hashes_unchanged": self.protected_hashes_unchanged,
            "tracked_state_unchanged": self.tracked_state_unchanged,
            "volatile_differences": list(self.volatile_differences),
            "unexpected_differences": list(self.unexpected_differences),
            "errors": list(self.errors),
        }


def capture_snapshot(
    repo_root: str | Path,
    protected_paths: Sequence[str] | None = None,
) -> RepositorySnapshot:
    """Capture a repository snapshot at the current state.

    Args:
        repo_root: Path to the git repository root.
        protected_paths: Repo-relative paths whose content hashes are recorded.
    """
    root = Path(repo_root).resolve(strict=True)
    branch = _git(root, ["branch", "--show-current"]).strip()
    head = _git(root, ["rev-parse", "HEAD"]).strip()
    status_raw = _git(root, ["status", "--porcelain=v1", "--untracked-files=all"])

    tracked: list[str] = []
    untracked: list[str] = []
    ignored: list[str] = []

    for line in status_raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("?? "):
            untracked.append(line[3:].replace("\\", "/"))
        elif line.startswith("!! "):
            ignored.append(line[3:].replace("\\", "/"))
        else:
            # Tracked change: XY where X=index status, Y=worktree status
            path = line[3:].replace("\\", "/")
            tracked.append(path)

    protected_hashes: dict[str, str] = {}
    if protected_paths:
        for path in protected_paths:
            file_path = root / path
            if file_path.is_file():
                protected_hashes[path] = sha256_file(file_path)

    return RepositorySnapshot(
        branch=branch,
        head=head,
        tracked_files=tuple(sorted(tracked)),
        untracked_files=tuple(sorted(untracked)),
        ignored_files=tuple(sorted(ignored)),
        protected_hashes=protected_hashes,
        git_status_raw=status_raw,
    )


def compare_snapshots(
    before: RepositorySnapshot,
    after: RepositorySnapshot,
    *,
    volatile_paths: frozenset[str] | None = None,
    snapshots_retained: bool = True,
) -> RepositoryIntegrityResult:
    """Compare two snapshots and classify the integrity result.

    CRITICAL: Volatile path exemptions may only tolerate explicitly permitted
    transient (untracked) state. They MUST NOT silently tolerate changes to
    tracked protected content.

    A volatile-path rule must never automatically authorize modification,
    deletion, or disappearance of a tracked protected file.

    Args:
        before: Pre-execution snapshot.
        after: Post-execution snapshot.
        volatile_paths: Set of repo-relative paths allowed to appear/disappear
            as untracked files. These must be transient artifacts (locks, temp files)
            that are NOT tracked in the repository.
        snapshots_retained: Whether status snapshots were successfully captured.
    """
    errors: list[str] = []
    volatile_diffs: list[dict[str, str]] = []
    unexpected_diffs: list[dict[str, str]] = []

    if volatile_paths is None:
        volatile_paths = frozenset()

    branch_unchanged = before.branch == after.branch
    head_unchanged = before.head == after.head
    protected_hashes_unchanged = before.protected_hashes == after.protected_hashes

    before_tracked = set(before.tracked_files)
    after_tracked = set(after.tracked_files)
    tracked_state_unchanged = before_tracked == after_tracked

    protected_invariants_unchanged = (
        branch_unchanged
        and head_unchanged
        and protected_hashes_unchanged
        and tracked_state_unchanged
    )

    if not snapshots_retained:
        unexpected_diffs.append(
            {"path": "<status-snapshots>", "change": "NOT_RETAINED"}
        )

    # --- Untracked differences ---
    before_untracked = set(before.untracked_files)
    after_untracked = set(after.untracked_files)

    removed_untracked = before_untracked - after_untracked
    added_untracked = after_untracked - before_untracked

    for path in sorted(removed_untracked):
        if path in volatile_paths:
            volatile_diffs.append({"path": path, "change": "DISAPPEARED"})
        else:
            unexpected_diffs.append({"path": path, "change": "DISAPPEARED"})

    for path in sorted(added_untracked):
        if path in volatile_paths:
            volatile_diffs.append({"path": path, "change": "APPEARED"})
        else:
            unexpected_diffs.append({"path": path, "change": "APPEARED"})

    # --- Critical: tracked file protection ---
    # A volatile-path entry must NEVER authorize changes to tracked files.
    # Even if a path is in volatile_paths, if it was or became tracked,
    # that is an integrity failure.
    for path in sorted(before_tracked - after_tracked):
        # A tracked file disappeared — always an integrity failure
        unexpected_diffs.append(
            {"path": path, "change": "TRACKED_FILE_DISAPPEARED"}
        )

    for path in sorted(after_tracked - before_tracked):
        # A new tracked file appeared — always an integrity failure
        unexpected_diffs.append(
            {"path": path, "change": "TRACKED_FILE_APPEARED"}
        )

    # --- Ignored changes ---
    before_ignored = set(before.ignored_files)
    after_ignored = set(after.ignored_files)
    if before_ignored != after_ignored:
        unexpected_diffs.append(
            {"path": "<ignored-status-set>", "change": "CHANGED"}
        )

    # --- Classify ---
    if protected_invariants_unchanged and not unexpected_diffs:
        if volatile_diffs:
            result = "VOLATILE_ONLY"
        else:
            result = "EXACT_MATCH"
    else:
        result = "INTEGRITY_FAILURE"

    return RepositoryIntegrityResult(
        result=result,
        branch_unchanged=branch_unchanged,
        head_unchanged=head_unchanged,
        protected_hashes_unchanged=protected_hashes_unchanged,
        tracked_state_unchanged=tracked_state_unchanged,
        volatile_differences=tuple(volatile_diffs),
        unexpected_differences=tuple(unexpected_diffs),
        errors=tuple(errors),
    )


def _git(repo_root: str | Path, argv: list[str]) -> str:
    """Run a git command and return stdout, or raise RepositoryGuardError."""
    try:
        result = subprocess.run(
            ["git", *argv],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RepositoryGuardError(
                f"git {' '.join(argv)} failed: {result.stderr.strip()}"
            )
        return result.stdout
    except FileNotFoundError:
        raise RepositoryGuardError("git executable not found")
    except subprocess.TimeoutExpired:
        raise RepositoryGuardError(f"git {' '.join(argv)} timed out")
