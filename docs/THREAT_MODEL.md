# Threat Model

## Assets Protected

1. **Source code** — protected from unauthorized modification
2. **Test suites** — protected from tampering (immutable read paths)
3. **Configuration** — protected from exposure (forbidden paths)
4. **Evidence trail** — protected from tampering (hash-verified manifest)
5. **Repository integrity** — protected from drift (snapshot comparison)

## Threat Actors

### Malicious Agent

An AI agent that intentionally tries to:
- Read files outside its scope
- Write to protected files
- Execute shell commands
- Access network resources
- Modify evidence
- Claim false outputs

Mitigation: Event policy fail-closed, path scope enforcement, tool allowlists.

### Buggy Agent

An AI agent that accidentally:
- Edits the wrong file
- Creates unexpected artifacts
- Breaks tests that previously passed

Mitigation: Patch scope-exact validation, repository guard snapshots.

### Compromised Adapter

An attacker who modifies the agent adapter to bypass normalization.

Mitigation: Adapter outputs go through the same deterministic core; the
adapter cannot skip gates.

## Attack Surface

| Entry Point | Risk | Mitigation |
|-------------|------|-----------|
| TaskSpec JSON | Medium | Contract validation + policy checks |
| Agent events | High | Fail-closed classification, path validation |
| Patch files | High | Repo-relative check, scope, apply-check |
| Evidence files | Medium | SHA-256 manifest, tamper detection |
| CLI arguments | Low | argparse validation, typed exit codes |

## Defense in Depth

The system uses multiple independent gates that must ALL pass:

1. TaskSpec structural validation
2. Policy compliance check
3. Event-by-event classification
4. Path-scope enforcement per event
5. Patch structural validation
6. Patch scope validation
7. Repository integrity comparison
8. Evidence manifest verification

A single gate failure blocks acceptance.
