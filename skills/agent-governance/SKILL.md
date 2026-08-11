# Agent Governance Skill

## When to Invoke

Invoke this skill when an autonomous coding agent is about to:

1. **Execute a task** — before the agent modifies any repository files, validate
   the TaskSpec and ensure deterministic governance gates pass.

2. **Review a completed task** — after the agent produces output, validate the
   patch, repository integrity, and evidence before accepting changes.

3. **Verify evidence** — when you need to confirm that all governance artifacts
   are present, hash-verified, and untampered.

## What This Skill Does

This skill integrates the deterministic governance CLI into agent workflows.
The governance engine validates:

- **TaskSpec** — scope of allowed reads, writes, immutable paths, and forbidden zones
- **Event Policy** — classifies each agent tool event, fail-closed on unknown/pathless actions
- **Patch Validation** — verifies patches are repo-relative, in-scope, and apply cleanly
- **Repository Guard** — before/after snapshots to detect unexpected changes
- **Gate Runner** — deterministic gates with PASS/FAIL, fail-closed on missing evidence
- **Evidence** — SHA-256 hashed manifest, tamper detection

## Core Enforcement

**The governance engine is deterministic Python code — not prompt instructions.**

Prompt instructions alone do not enforce security. The deterministic CLI must
be invoked at the appropriate points in the agent lifecycle.

## Usage

### Pre-execution

```bash
# Validate the TaskSpec
agent-governance validate-task task_spec.json --policy

# Check state transitions
agent-governance list-transitions
agent-governance check-transition --from-state NEW --to-state PLANNING --actor ORCHESTRATOR
```

### Post-execution

```bash
# Validate the event stream
agent-governance validate-events --task task_spec.json --events events.json --workspace /path/to/repo

# Validate the patch
agent-governance validate-patch --task task_spec.json --patch changes.diff --expected src/calculator.py

# Verify evidence integrity
agent-governance verify-evidence evidence/

# Compare repository snapshots
agent-governance compare-repo --before before.json --after after.json
```

## Integration Points

### With Claude Code

When Claude Code is executing a governed task:

1. **Before execution**: Run `validate-task` with the TaskSpec
2. **After execution**: Run `validate-events`, `validate-patch`, and `verify-evidence`
3. **On completion**: Run `compare-repo` if snapshots were captured

### With Other Agents

The same CLI works with any agent provider. Normalize agent events into the
generic GovernanceEvent format and pass through the event policy classifier.

## Important

- This Skill is an integration layer, NOT the enforcement engine
- Deterministic governance comes from the Python library and CLI
- Always verify evidence hashes before accepting agent output
- Patch validation must include scope-exact checks when expected files are known
