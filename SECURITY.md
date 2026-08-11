# Security

## Threat Model

The Agent Governance Kit addresses the following threats from autonomous
coding agents:

| Threat | Mitigation |
|--------|-----------|
| Out-of-scope file reads | TaskSpec read_paths + event policy fail-closed |
| Out-of-scope file writes | TaskSpec write_paths + forbidden_paths always win |
| Pathless filesystem actions | Event policy rejects actions without deterministic paths |
| Unknown tool usage | UNKNOWN tools fail closed |
| Patch outside write scope | Patch validator enforces scope on every changed file |
| Unexpected repository changes | Repository guard compares before/after snapshots |
| Evidence tampering | SHA-256 manifest with tamper detection |
| Agent self-promoting state | Deterministic state machine — models never self-promote |
| Structured result misreporting | StructuredOutput transport explicitly validated |

## What This Does NOT Protect Against

- Malicious code already present in the repository before governance
- Supply chain attacks on the governance tool itself
- Kernel-level or hardware-level attacks
- Social engineering of human reviewers
- Bugs in the governance code (defense in depth recommended)

## Design Principles

1. **Fail closed**: Unknown inputs default to rejection
2. **Deterministic**: Same inputs always produce same outputs
3. **Provider-agnostic**: Governance works regardless of which AI provider is used
4. **Defense in depth**: Multiple independent gates must all pass

## Reporting Issues

If you discover a security issue in the governance logic itself, please
open a GitHub issue. Do not include sensitive information.
