"""Tests for deterministic gate runner."""

import pytest

from agent_governance.gate_runner import (
    GateResult,
    GateRunner,
    GateRunnerResult,
    GateStatus,
    make_gate,
)


class TestGateResult:
    """Tests for individual gate results."""

    def test_pass_gate(self):
        g = make_gate("test_gate", True, "all good")
        assert g.status == GateStatus.PASS
        assert g.passed

    def test_fail_gate(self):
        g = make_gate("test_gate", False, "something wrong")
        assert g.status == GateStatus.FAIL
        assert not g.passed

    def test_gate_result_to_dict(self):
        g = make_gate("my_gate", True, "reason", {"key": "val"})
        d = g.to_dict()
        assert d["name"] == "my_gate"
        assert d["status"] == "PASS"
        assert d["reason"] == "reason"
        assert d["evidence"] == {"key": "val"}

    def test_gate_skip(self):
        g = GateResult(name="skipped", status=GateStatus.SKIP, reason="n/a")
        assert not g.passed


class TestGateRunner:
    """Tests for the gate runner."""

    def test_all_pass(self):
        runner = GateRunner()
        runner.add_gate("gate_1", lambda: make_gate("gate_1", True, "ok"))
        runner.add_gate("gate_2", lambda: make_gate("gate_2", True, "ok"))
        result = runner.run()
        assert result.all_pass
        assert result.verdict == "ACCEPT"
        assert result.passed == 2
        assert result.failed == 0

    def test_one_fails_required(self):
        """Gate failure prevents acceptance."""
        runner = GateRunner()
        runner.add_gate("pass_gate", lambda: make_gate("pass_gate", True, "ok"))
        runner.add_gate("fail_gate", lambda: make_gate("fail_gate", False, "nope"))
        result = runner.run()
        assert not result.all_pass
        assert result.verdict == "REJECT"
        assert "fail_gate" in result.failed_gate_names

    def test_non_required_failure_allows_accept(self):
        runner = GateRunner()
        runner.add_gate("required_pass", lambda: make_gate("required_pass", True, "ok"))
        runner.add_gate(
            "optional_fail",
            lambda: make_gate("optional_fail", False, "advisory"),
            required=False,
        )
        result = runner.run()
        # optional failure doesn't block acceptance
        assert result.all_pass  # required gates all passed

    def test_missing_evidence_fails_closed(self):
        """A required gate that cannot execute must fail closed."""
        runner = GateRunner(fail_closed=True)

        def broken_check():
            raise RuntimeError("evidence database is offline")

        runner.add_gate("evidence_gate", broken_check)
        result = runner.run()
        assert not result.all_pass
        assert result.verdict == "REJECT"
        assert "evidence_gate" in result.failed_gate_names

    def test_missing_evidence_non_required_skips(self):
        runner = GateRunner(fail_closed=True)

        def broken_check():
            raise RuntimeError("optional evidence missing")

        runner.add_gate("optional_gate", broken_check, required=False)
        result = runner.run()
        assert result.all_pass  # non-required failures don't block

    def test_skip_status(self):
        runner = GateRunner(fail_closed=False)
        runner.add_gate(
            "skip_gate",
            lambda: GateResult(name="skip_gate", status=GateStatus.SKIP, reason="n/a"),
        )
        result = runner.run()
        assert result.skipped == 1
        assert result.passed == 0

    def test_stable_verdict(self):
        """Gate runner produces a stable final verdict."""
        runner = GateRunner()
        runner.add_gate("g1", lambda: make_gate("g1", True, "ok"))
        runner.add_gate("g2", lambda: make_gate("g2", True, "ok"))
        a = runner.run()
        b = runner.run()
        assert a.verdict == b.verdict
        assert a.to_dict() == b.to_dict()

    def test_gate_runner_result_to_dict(self):
        runner = GateRunner()
        runner.add_gate("g1", lambda: make_gate("g1", True, "ok"))
        result = runner.run()
        d = result.to_dict()
        assert d["verdict"] == "ACCEPT"
        assert len(d["gates"]) == 1
