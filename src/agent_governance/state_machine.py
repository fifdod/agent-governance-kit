"""Deterministic state machine for agent-control orchestration.

States are controlled by deterministic orchestration code.
Models must never self-promote state.
Terminal states are immutable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentControlState(str, Enum):
    """Provider-agnostic agent control states."""

    NEW = "NEW"
    PLANNING = "PLANNING"
    PLAN_VALIDATION = "PLAN_VALIDATION"
    HUMAN_GATE_REQUIRED = "HUMAN_GATE_REQUIRED"
    EXECUTION_WORKSPACE_PREPARING = "EXECUTION_WORKSPACE_PREPARING"
    AGENT_RUNNING = "AGENT_RUNNING"
    AGENT_FAILED = "AGENT_FAILED"
    AGENT_COMPLETED = "AGENT_COMPLETED"
    DETERMINISTIC_VALIDATION = "DETERMINISTIC_VALIDATION"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    REVIEWING = "REVIEWING"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"
    TIMEOUT = "TIMEOUT"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    POLICY_VIOLATION = "POLICY_VIOLATION"


class TransitionActor(str, Enum):
    """Who or what can trigger a state transition."""

    ORCHESTRATOR = "ORCHESTRATOR"
    PLANNER = "PLANNER"
    EXECUTOR = "EXECUTOR"
    REVIEWER = "REVIEWER"
    HUMAN = "HUMAN"


@dataclass(frozen=True)
class Transition:
    """A single allowed state transition."""

    from_state: AgentControlState
    to_state: AgentControlState
    actor: TransitionActor
    reason: str


TERMINAL_STATES = frozenset(
    {
        AgentControlState.ACCEPTED,
        AgentControlState.BLOCKED,
        AgentControlState.TIMEOUT,
        AgentControlState.BUDGET_EXCEEDED,
        AgentControlState.POLICY_VIOLATION,
    }
)


_TRANSITIONS: tuple[Transition, ...] = (
    # Planning phase
    Transition(AgentControlState.NEW, AgentControlState.PLANNING, TransitionActor.ORCHESTRATOR, "start planning"),
    Transition(AgentControlState.PLANNING, AgentControlState.PLAN_VALIDATION, TransitionActor.ORCHESTRATOR, "planner output captured"),
    Transition(AgentControlState.PLANNING, AgentControlState.BLOCKED, TransitionActor.ORCHESTRATOR, "planner cannot produce safe spec"),
    Transition(AgentControlState.PLANNING, AgentControlState.TIMEOUT, TransitionActor.ORCHESTRATOR, "planner timed out"),
    # Plan validation
    Transition(AgentControlState.PLAN_VALIDATION, AgentControlState.EXECUTION_WORKSPACE_PREPARING, TransitionActor.ORCHESTRATOR, "task spec passed deterministic gates"),
    Transition(AgentControlState.PLAN_VALIDATION, AgentControlState.HUMAN_GATE_REQUIRED, TransitionActor.ORCHESTRATOR, "task spec requires approval"),
    Transition(AgentControlState.PLAN_VALIDATION, AgentControlState.VALIDATION_FAILED, TransitionActor.ORCHESTRATOR, "task spec failed schema or evidence checks"),
    Transition(AgentControlState.PLAN_VALIDATION, AgentControlState.POLICY_VIOLATION, TransitionActor.ORCHESTRATOR, "task spec violates hard policy"),
    # Human gate
    Transition(AgentControlState.HUMAN_GATE_REQUIRED, AgentControlState.EXECUTION_WORKSPACE_PREPARING, TransitionActor.ORCHESTRATOR, "human approval recorded"),
    Transition(AgentControlState.HUMAN_GATE_REQUIRED, AgentControlState.BLOCKED, TransitionActor.ORCHESTRATOR, "human approval denied or unavailable"),
    # Execution
    Transition(AgentControlState.EXECUTION_WORKSPACE_PREPARING, AgentControlState.AGENT_RUNNING, TransitionActor.ORCHESTRATOR, "workspace prepared"),
    Transition(AgentControlState.EXECUTION_WORKSPACE_PREPARING, AgentControlState.POLICY_VIOLATION, TransitionActor.ORCHESTRATOR, "workspace preparation violated policy"),
    Transition(AgentControlState.EXECUTION_WORKSPACE_PREPARING, AgentControlState.BLOCKED, TransitionActor.ORCHESTRATOR, "workspace cannot be prepared"),
    Transition(AgentControlState.AGENT_RUNNING, AgentControlState.AGENT_COMPLETED, TransitionActor.ORCHESTRATOR, "executor exited with structured result"),
    Transition(AgentControlState.AGENT_RUNNING, AgentControlState.AGENT_FAILED, TransitionActor.ORCHESTRATOR, "executor failed"),
    Transition(AgentControlState.AGENT_RUNNING, AgentControlState.TIMEOUT, TransitionActor.ORCHESTRATOR, "executor timeout"),
    Transition(AgentControlState.AGENT_RUNNING, AgentControlState.POLICY_VIOLATION, TransitionActor.ORCHESTRATOR, "runtime policy violation detected"),
    Transition(AgentControlState.AGENT_FAILED, AgentControlState.REWORK_REQUIRED, TransitionActor.ORCHESTRATOR, "retry budget remains"),
    Transition(AgentControlState.AGENT_FAILED, AgentControlState.BLOCKED, TransitionActor.ORCHESTRATOR, "executor failure without retry budget"),
    # Validation
    Transition(AgentControlState.AGENT_COMPLETED, AgentControlState.DETERMINISTIC_VALIDATION, TransitionActor.ORCHESTRATOR, "start deterministic validation"),
    Transition(AgentControlState.DETERMINISTIC_VALIDATION, AgentControlState.REVIEWING, TransitionActor.ORCHESTRATOR, "deterministic validation passed"),
    Transition(AgentControlState.DETERMINISTIC_VALIDATION, AgentControlState.VALIDATION_FAILED, TransitionActor.ORCHESTRATOR, "deterministic validation failed"),
    Transition(AgentControlState.DETERMINISTIC_VALIDATION, AgentControlState.POLICY_VIOLATION, TransitionActor.ORCHESTRATOR, "forbidden change or command detected"),
    # Review
    Transition(AgentControlState.REVIEWING, AgentControlState.ACCEPTED, TransitionActor.ORCHESTRATOR, "reviewer verdict accept"),
    Transition(AgentControlState.REVIEWING, AgentControlState.REWORK_REQUIRED, TransitionActor.ORCHESTRATOR, "reviewer verdict rework"),
    Transition(AgentControlState.REVIEWING, AgentControlState.REVIEW_REJECTED, TransitionActor.ORCHESTRATOR, "reviewer verdict rejected"),
    Transition(AgentControlState.REVIEWING, AgentControlState.BLOCKED, TransitionActor.ORCHESTRATOR, "reviewer verdict blocked"),
    Transition(AgentControlState.REVIEWING, AgentControlState.HUMAN_GATE_REQUIRED, TransitionActor.ORCHESTRATOR, "reviewer requests human decision"),
    # Rejection / rework
    Transition(AgentControlState.REVIEW_REJECTED, AgentControlState.REWORK_REQUIRED, TransitionActor.ORCHESTRATOR, "retry budget remains after rejection"),
    Transition(AgentControlState.REVIEW_REJECTED, AgentControlState.BLOCKED, TransitionActor.ORCHESTRATOR, "rejection without retry budget"),
    Transition(AgentControlState.REWORK_REQUIRED, AgentControlState.EXECUTION_WORKSPACE_PREPARING, TransitionActor.ORCHESTRATOR, "start bounded rework cycle"),
    Transition(AgentControlState.REWORK_REQUIRED, AgentControlState.BUDGET_EXCEEDED, TransitionActor.ORCHESTRATOR, "rework budget exhausted"),
)


def transition_table() -> tuple[Transition, ...]:
    """Return the full deterministic transition table."""
    return _TRANSITIONS


def allowed_transitions(state: AgentControlState) -> tuple[Transition, ...]:
    """Return all allowed transitions from a given state."""
    return tuple(t for t in _TRANSITIONS if t.from_state == state)


def can_transition(
    from_state: AgentControlState,
    to_state: AgentControlState,
    actor: TransitionActor,
) -> bool:
    """Check whether a transition is allowed."""
    return any(
        t.from_state == from_state
        and t.to_state == to_state
        and t.actor == actor
        for t in _TRANSITIONS
    )


def assert_transition(
    from_state: AgentControlState,
    to_state: AgentControlState,
    actor: TransitionActor,
) -> None:
    """Assert a transition is valid, raising ValueError otherwise."""
    if from_state in TERMINAL_STATES:
        raise ValueError(f"{from_state.value} is terminal")
    if not can_transition(from_state, to_state, actor):
        raise ValueError(
            f"{actor.value} cannot transition {from_state.value} -> {to_state.value}"
        )
