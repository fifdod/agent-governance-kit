"""Tests for repository guard — snapshot and integrity comparison.

Includes the critical tracked-volatile regression test:
A volatile-path exemption must NEVER authorize changes to tracked protected content.
"""

import pytest

from agent_governance.repo_guard import (
    RepositoryGuardError,
    RepositoryIntegrityResult,
    RepositorySnapshot,
    capture_snapshot,
    compare_snapshots,
)


def _snapshot(
    branch="main",
    head="a" * 40,
    tracked=(),
    untracked=(),
    ignored=(),
    protected=None,
    status_raw="",
):
    return RepositorySnapshot(
        branch=branch,
        head=head,
        tracked_files=tuple(tracked),
        untracked_files=tuple(untracked),
        ignored_files=tuple(ignored),
        protected_hashes=protected or {},
        git_status_raw=status_raw,
    )


class TestRepositorySnapshot:
    """Tests for snapshot capture and comparison."""

    def test_exact_match(self):
        before = _snapshot(
            tracked=("src/main.py", "README.md"),
        )
        after = _snapshot(
            tracked=("src/main.py", "README.md"),
        )
        result = compare_snapshots(before, after)
        assert result.result == "EXACT_MATCH"
        assert result.passed

    def test_branch_changed(self):
        before = _snapshot(branch="main")
        after = _snapshot(branch="feature")
        result = compare_snapshots(before, after)
        assert result.result == "INTEGRITY_FAILURE"
        assert not result.branch_unchanged

    def test_head_changed(self):
        before = _snapshot(head="a" * 40)
        after = _snapshot(head="b" * 40)
        result = compare_snapshots(before, after)
        assert result.result == "INTEGRITY_FAILURE"
        assert not result.head_unchanged

    def test_protected_hash_changed(self):
        before = _snapshot(protected={"config.json": "hash_a"})
        after = _snapshot(protected={"config.json": "hash_b"})
        result = compare_snapshots(before, after)
        assert result.result == "INTEGRITY_FAILURE"
        assert not result.protected_hashes_unchanged

    def test_tracked_state_changed(self):
        before = _snapshot(tracked=("a.py", "b.py"))
        after = _snapshot(tracked=("a.py",))
        result = compare_snapshots(before, after)
        assert result.result == "INTEGRITY_FAILURE"
        assert not result.tracked_state_unchanged

    def test_volatile_only(self):
        """Volatile-path only changes are tolerated."""
        before = _snapshot(
            untracked=(".lock",),
        )
        after = _snapshot(
            untracked=(),
        )
        result = compare_snapshots(
            before, after, volatile_paths=frozenset({".lock"})
        )
        assert result.result == "VOLATILE_ONLY"
        assert result.passed
        assert len(result.volatile_differences) == 1

    def test_volatile_appears(self):
        before = _snapshot(untracked=())
        after = _snapshot(untracked=(".lock",))
        result = compare_snapshots(
            before, after, volatile_paths=frozenset({".lock"})
        )
        assert result.result == "VOLATILE_ONLY"
        assert result.passed

    def test_unexpected_untracked(self):
        before = _snapshot(untracked=())
        after = _snapshot(untracked=("unexpected_file",))
        result = compare_snapshots(before, after)
        assert result.result == "INTEGRITY_FAILURE"

    def test_unexpected_untracked_disappeared(self):
        before = _snapshot(untracked=("mystery_file",))
        after = _snapshot(untracked=())
        result = compare_snapshots(before, after)
        assert result.result == "INTEGRITY_FAILURE"

    def test_ignored_changed(self):
        before = _snapshot(ignored=("build/",))
        after = _snapshot(ignored=("build/", "dist/"))
        result = compare_snapshots(before, after)
        assert result.result == "INTEGRITY_FAILURE"

    def test_snapshots_not_retained(self):
        before = _snapshot()
        after = _snapshot()
        result = compare_snapshots(before, after, snapshots_retained=False)
        assert result.result == "INTEGRITY_FAILURE"


class TestTrackedVolatileRegression:
    """CRITICAL: Volatile-path exemptions must never authorize tracked changes."""

    def test_volatile_path_does_not_exempt_tracked_disappearance(self):
        """A tracked protected file cannot be exempted merely because
        its pathname matches a volatile-path entry."""
        before = _snapshot(
            tracked=("state/runtime.lock",),
            untracked=(),
        )
        after = _snapshot(
            tracked=(),  # tracked file disappeared!
            untracked=(),
        )
        # Even if "state/runtime.lock" is in volatile_paths, it was TRACKED
        # so its disappearance is an integrity failure.
        result = compare_snapshots(
            before, after, volatile_paths=frozenset({"state/runtime.lock"})
        )
        assert result.result == "INTEGRITY_FAILURE"
        assert any(
            "TRACKED_FILE_DISAPPEARED" in d.get("change", "")
            for d in result.unexpected_differences
        )

    def test_volatile_path_does_not_exempt_tracked_appearance(self):
        """A new tracked file that happens to match a volatile path is still
        an integrity failure."""
        before = _snapshot(
            tracked=("src/main.py",),
            untracked=(),
        )
        after = _snapshot(
            tracked=("src/main.py", "state/runtime.lock"),
            untracked=(),
        )
        result = compare_snapshots(
            before, after, volatile_paths=frozenset({"state/runtime.lock"})
        )
        assert result.result == "INTEGRITY_FAILURE"
        assert any(
            "TRACKED_FILE_APPEARED" in d.get("change", "")
            for d in result.unexpected_differences
        )

    def test_volatile_path_works_for_untracked_only(self):
        """Volatile paths only exempt untracked files."""
        before = _snapshot(
            tracked=("src/main.py",),
            untracked=(".lock",),
        )
        after = _snapshot(
            tracked=("src/main.py",),
            untracked=(),
        )
        result = compare_snapshots(
            before, after, volatile_paths=frozenset({".lock"})
        )
        assert result.result == "VOLATILE_ONLY"
        assert result.passed

    def test_volatile_path_not_in_tracked_set_untouched(self):
        """A normal volatile pattern doesn't touch tracked files."""
        before = _snapshot(
            tracked=("src/main.py", "README.md"),
            untracked=("temp.tmp",),
        )
        after = _snapshot(
            tracked=("src/main.py", "README.md"),
            untracked=(),
        )
        result = compare_snapshots(
            before, after, volatile_paths=frozenset({"temp.tmp"})
        )
        # temp.tmp is volatile and untracked — OK
        assert result.result == "VOLATILE_ONLY"
