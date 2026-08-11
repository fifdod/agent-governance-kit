# Architecture

## Overview

The Agent Governance Kit is a deterministic, provider-agnostic governance layer
for autonomous coding agents. It validates, classifies, verifies, and records
every step of an agent's execution.

## Layers

```
┌─────────────────────────────────────────┐
│              Agent Adapters              │  Provider-specific
│  (claude.py, codex.py → base.py)        │
├─────────────────────────────────────────┤
│           Deterministic Core             │
│  ┌───────────┐  ┌──────────────────┐    │
│  │ TaskSpec   │  │  Event Policy     │    │
│  │ v2         │  │  Classifier       │    │
│  └───────────┘  └──────────────────┘    │
│  ┌───────────┐  ┌──────────────────┐    │
│  │ Policy     │  │  State Machine    │    │
│  │ Engine     │  │  (17 states)      │    │
│  └───────────┘  └──────────────────┘    │
│  ┌───────────┐  ┌──────────────────┐    │
│  │ Patch      │  │  Repository       │    │
│  │ Validator  │  │  Guard            │    │
│  └───────────┘  └──────────────────┘    │
│  ┌───────────┐  ┌──────────────────┐    │
│  │ Gate       │  │  Evidence         │    │
│  │ Runner     │  │  System           │    │
│  └───────────┘  └──────────────────┘    │
├─────────────────────────────────────────┤
│                 CLI                      │  User interface
└─────────────────────────────────────────┘
```

## Data Flow

1. **Task Planning** → TaskSpec v2 (validated by contracts + policy)
2. **Agent Execution** → Raw events (normalized by adapters)
3. **Event Classification** → Normalized events (fail-closed)
4. **Deterministic Validation** → Gates (patch, repo, evidence)
5. **Review** → Advisory verdict (separated from deterministic gates)
6. **Acceptance** → Terminal state (only if ALL required gates pass)

## Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `contracts.py` | JSON schema validation (stdlib) |
| `task_spec.py` | TaskSpec v2 data model + validation |
| `policy.py` | Static policy engine: forbidden patterns, limits |
| `event_policy.py` | Event normalization + classification |
| `state_machine.py` | Deterministic state transitions |
| `patch_validator.py` | Patch parsing, scope, identity verification |
| `repo_guard.py` | Repository snapshot + integrity comparison |
| `gate_runner.py` | Deterministic gate execution |
| `evidence.py` | Evidence bundle, manifest, tamper detection |
| `cli.py` | Command-line interface |
| `runtime_utils.py` | SHA-256, atomic writes, path normalization |

## Design Decisions

### Provider-Agnostic Core

The core does not import or depend on any specific AI provider (Anthropic,
OpenAI, etc.). Agent-specific adapters normalize provider events into the
generic `GovernanceEvent` type.

### Fail-Closed by Default

- Unknown tools → violation
- Pathless filesystem actions → violation
- Missing evidence → gate failure
- Unparseable patches → validation failure

### No Self-Promotion

The deterministic state machine ensures that only the orchestrator (code)
can transition states. Models report results; code determines state.

### Volatile vs Tracked

The repository guard distinguishes between untracked volatile artifacts
(locks, temp files) and tracked protected content. A volatile-path
exemption never authorizes changes to tracked files.
