# Extraction Methodology

## Source

This project was extracted from a private agent-governance system that had been
tested with real autonomous coding agent canaries using Codex planners, Claude
executors, and Codex reviewers.

## Extraction Method

The extraction followed a structured methodology:

1. **Source discovery** — Inspected current and historical source modules
2. **Behavioral analysis** — Understood runtime-verified governance behaviors
3. **Module classification** — Each source file categorized into one of:
   - `COPY_AND_SANITIZE`: Already generic, minimal changes needed
   - `REIMPLEMENT_FROM_BEHAVIOR`: Rewrote from scratch preserving behavior
   - `REWRITE_AS_INTERFACE`: Abstracted provider-specific details
   - `WRITE_NEW`: Created without source reference
   - `DO_NOT_COPY`: Excluded entirely (business logic, private data)

## Sanitization

All proprietary references were removed:
- No business logic (trading, factors, strategies)
- No private paths or machine identities
- No credentials or API keys
- No Hunter-specific terminology in core code
- Provider-agnostic naming throughout

## New Implementation

The v0.1 public implementation is an independent codebase:
- New Git repository with zero history relationship to source
- All code written specifically for this project
- No source files copied verbatim without sanitization
- No private runtime evidence published

## Provenance

The originating private control system executed approximately:
- 5 Codex planner invocations
- 4 Claude executor invocations
- 2 Codex reviewer invocations

It reached a 273/273 deterministic regression result during its latest canary.
This public v0.1 is a subset extraction and does not contain all capabilities
of the private system.
