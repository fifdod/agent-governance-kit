# Agent Governance Kit

**Fail-closed governance, task-scope enforcement, patch verification, and evidence layer for autonomous coding agents.**

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Problem

Autonomous coding agents can modify code outside intended scope, misreport results,
or produce unverifiable patches. Trusting an agent's self-reported output without
deterministic verification creates risk.

## Solution

A **deterministic governance layer** that wraps around the agent. It validates
scope, classifies events, verifies patches, guards repository integrity, and
produces hash-verifiable evidence — before accepting any agent output.

```
TaskSpec → Policy → Event Stream → Event Policy → Gates → Patch Validation → Repository Guard → Evidence
```

## What v0.1 Implements

| Component | Description |
|-----------|-------------|
| **TaskSpec v2** | Four-category path semantics: read, write, immutable-read, forbidden |
| **Static Policy Engine** | Fail-closed policy with global forbidden patterns and limits |
| **Event Policy Classifier** | Normalizes agent tool events into action classes; unknown/pathless fail closed |
| **Patch Validator** | Repo-relative paths, scope enforcement, rename parsing, content hashing |
| **Repository Guard** | Before/after snapshots; tracked-volatile distinction; integrity comparison |
| **Gate Runner** | Deterministic named gates; fail-closed on missing evidence |
| **Evidence System** | SHA-256 manifest, JSONL event stream, tamper detection |
| **CLI** | Full command-line interface with typed exit codes |
| **State Machine** | Provider-agnostic deterministic state transitions |

## What the Private Source System Has Runtime-Validated

This project was extracted from an agent-governance system tested with real Codex
planner, Claude executor, and Codex reviewer canaries. The originating system
executed approximately: 5 Codex planner invocations, 4 Claude executor
invocations, and 2 Codex reviewer invocations. The originating private control
system had reached a 273/273 deterministic regression result during its latest
canary.

v0.1 of this public repository is an independent extraction — it does **not**
contain all capabilities of the private system.

## Installation

```bash
pip install -e .
```

Requirements: Python 3.11+. Stdlib-only core. `pytest` for development/testing.

## Quick Start

### Validate a TaskSpec

```bash
agent-governance validate-task examples/demo_scenarios/01_valid_fix.json --policy
```

### Validate Agent Events

```bash
agent-governance validate-events \
  --task task_spec.json \
  --events agent_events.json \
  --workspace /path/to/repo
```

### Validate a Patch

```bash
agent-governance validate-patch \
  --task task_spec.json \
  --patch changes.diff \
  --expected src/calculator.py
```

### Verify Evidence

```bash
agent-governance verify-evidence evidence_run_001/
```

### Run the Demo

```bash
cd examples/
python -m pytest ../tests/ -v
```

## Library Usage

```python
from agent_governance.task_spec import build_task_spec
from agent_governance.event_policy import evaluate_event_stream
from agent_governance.patch_validator import validate_patch

task = build_task_spec({...})
result = evaluate_event_stream(events, task, workspace_root="/path/to/repo")
if not result.valid:
    for v in result.violations:
        print(f"{v.code}: {v.message}")
```

## Architecture

- **Deterministic core** (`src/agent_governance/`): Provider-agnostic governance logic
- **Agent adapters** (`src/agent_governance/agent_adapters/`): Provider-specific event normalization
- **Schemas** (`schemas/`): JSON Schema for TaskSpec v2
- **Config** (`config/`): Default fail-closed policy
- **Skills** (`skills/`): Claude Code SKILL.md integration

## Known Limitations (v0.1)

- No automatic real model execution in v0.1 core (interfaces present)
- No cross-platform process-tree supervisor
- No full resume/rework runtime
- No automatic reviewer execution
- This is not "production proven" — it is v0.1 of an extracted governance toolkit

## License

MIT License — see [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md) for the threat model and responsible disclosure.

## Provenance

See [docs/EXTRACTION.md](docs/EXTRACTION.md) for the extraction methodology
and relationship to the private source system.
