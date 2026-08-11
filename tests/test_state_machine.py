"""Tests for deterministic state machine."""

import pytest

from agent_governance.state_machine import (
    AgentControlState,
    TransitionActor,
    TERMINAL_STATES,
    Transition,
    allowed_transitions,
    assert_transition,
    can_transition,
    transition_table,
)


class TestStateMachine:
    """Tests for deterministic state transitions."""

    def test_transition_table_is_stable(self):
        a = transition_table()
        b = transition_table()
        assert a == b

    def test_known_transition(self):
        assert can_transition(
            AgentControlState.NEW,
            AgentControlState.PLANNING,
            TransitionActor.ORCHESTRATOR,
        )

    def test_disallowed_transition(self):
        # Cannot jump from NEW directly to ACCEPTED
        assert not can_transition(
            AgentControlState.NEW,
            AgentControlState.ACCEPTED,
            TransitionActor.ORCHESTRATOR,
        )

    def test_assert_valid_transition(self):
        assert_transition(
            AgentControlState.NEW,
            AgentControlState.PLANNING,
            TransitionActor.ORCHESTRATOR,
        )

    def test_assert_invalid_transition(self):
        with pytest.raises(ValueError, match="cannot transition"):
            assert_transition(
                AgentControlState.NEW,
                AgentControlState.ACCEPTED,
                TransitionActor.ORCHESTRATOR,
            )

    def test_terminal_no_transitions(self):
        """Terminal states must be immutable — no transitions out."""
        for state in TERMINAL_STATES:
            with pytest.raises(ValueError, match="terminal"):
                assert_transition(state, AgentControlState.NEW, TransitionActor.ORCHESTRATOR)

    def test_allowed_transitions_from_new(self):
        transitions = allowed_transitions(AgentControlState.NEW)
        assert len(transitions) == 1
        assert transitions[0].to_state == AgentControlState.PLANNING

    def test_all_terminal_states(self):
        assert AgentControlState.ACCEPTED in TERMINAL_STATES
        assert AgentControlState.BLOCKED in TERMINAL_STATES
        assert AgentControlState.TIMEOUT in TERMINAL_STATES
        assert AgentControlState.BUDGET_EXCEEDED in TERMINAL_STATES
        assert AgentControlState.POLICY_VIOLATION in TERMINAL_STATES

    def test_complete_accept_path(self):
        """Verify a complete path from NEW to ACCEPTED."""
        path = [
            (AgentControlState.NEW, AgentControlState.PLANNING),
            (AgentControlState.PLANNING, AgentControlState.PLAN_VALIDATION),
            (AgentControlState.PLAN_VALIDATION, AgentControlState.EXECUTION_WORKSPACE_PREPARING),
            (AgentControlState.EXECUTION_WORKSPACE_PREPARING, AgentControlState.AGENT_RUNNING),
            (AgentControlState.AGENT_RUNNING, AgentControlState.AGENT_COMPLETED),
            (AgentControlState.AGENT_COMPLETED, AgentControlState.DETERMINISTIC_VALIDATION),
            (AgentControlState.DETERMINISTIC_VALIDATION, AgentControlState.REVIEWING),
            (AgentControlState.REVIEWING, AgentControlState.ACCEPTED),
        ]
        for from_s, to_s in path:
            assert can_transition(from_s, to_s, TransitionActor.ORCHESTRATOR)

    def test_planner_failure_path(self):
        """Planner/process failure must block execution."""
        assert can_transition(
            AgentControlState.PLANNING,
            AgentControlState.BLOCKED,
            TransitionActor.ORCHESTRATOR,
        )

    def test_agent_failure_path(self):
        """Agent failure with rework budget."""
        assert can_transition(
            AgentControlState.AGENT_FAILED,
            AgentControlState.REWORK_REQUIRED,
            TransitionActor.ORCHESTRATOR,
        )
        assert can_transition(
            AgentControlState.AGENT_FAILED,
            AgentControlState.BLOCKED,
            TransitionActor.ORCHESTRATOR,
        )

    def test_review_reject_path(self):
        """Reviewer rejection path."""
        assert can_transition(
            AgentControlState.REVIEWING,
            AgentControlState.REVIEW_REJECTED,
            TransitionActor.ORCHESTRATOR,
        )
        assert can_transition(
            AgentControlState.REVIEW_REJECTED,
            AgentControlState.REWORK_REQUIRED,
            TransitionActor.ORCHESTRATOR,
        )

    def test_policy_violation_terminal(self):
        """Policy violations are terminal."""
        assert can_transition(
            AgentControlState.AGENT_RUNNING,
            AgentControlState.POLICY_VIOLATION,
            TransitionActor.ORCHESTRATOR,
        )

    def test_reviewer_result_is_advisory(self):
        """Reviewer result (ACCEPT/REWORK/REJECT) is advisory — orchestrator owns the transition."""
        # The orchestrator determines the actual state change from reviewer output
        assert can_transition(
            AgentControlState.REVIEWING,
            AgentControlState.ACCEPTED,
            TransitionActor.ORCHESTRATOR,
        )
        # The reviewer doesn't directly transition states
        assert not can_transition(
            AgentControlState.REVIEWING,
            AgentControlState.ACCEPTED,
            TransitionActor.REVIEWER,
        )

    def test_provider_agnostic_names(self):
        """State names must be provider-agnostic."""
        assert AgentControlState.AGENT_RUNNING.value == "AGENT_RUNNING"
        assert AgentControlState.AGENT_COMPLETED.value == "AGENT_COMPLETED"
        assert AgentControlState.REVIEWING.value == "REVIEWING"
        # Verify no Claude/Codex hardcoding in state names
        for state in AgentControlState:
            assert "CLAUDE" not in state.value
            assert "CODEX" not in state.value
