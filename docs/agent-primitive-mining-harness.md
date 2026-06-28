# Agent Primitive Mining harness

Purpose: make trend-repo mining repeatable and useful for Hermes/Bertus/AW Lite. The output is not a hype list and not a fork decision. The output is a small, evidenced primitive translated into our stack, with verification or a clear no-action verdict.

## Decision rule

Mine a repository only when it can improve one of these primitives:

1. repo intelligence: repo map, diff/apply, commit discipline;
2. approval and safety UX: visible tool diffs, terminal risk, publish/destructive gates;
3. durable execution: sandbox/workspace lifecycle, task state, retries, logs;
4. MCP/capability layer: tools/resources/prompts split, import/status, trust gates;
5. context and memory: bounded retrieval, provenance, conflict/update model;
6. eval and observability: trajectories, task grading, local regression harnesses.

If a repo does not map to one of those, do not mine it now.

## Mining loop

### 1. Pick the primitive first

Write the target as a capability, not a repo name:

```text
Primitive: repo-map assisted patch planning for Hermes repo work
Candidate repos: Aider, Codex CLI
Expected Hermes surface: docs + parser/check primitive + AW Lite verification gate
```

Bad:

```text
Mine Aider because it is popular.
```

### 2. Inspect source and status

For every source repo record:

- repository URL;
- local clone path, if cloned;
- commit SHA or release tag;
- license;
- maintenance/status signal;
- exact source files/docs inspected.

Do not copy code until the license and fit are clear. Most outputs should be pattern translations, not pasted code.

### 3. Extract the smallest transferable pattern

Use this format:

| Field | Required answer |
|---|---|
| Pattern | What reusable idea exists? |
| Source evidence | Repo paths, docs, code lines, commands inspected |
| Why it works there | The product/user problem it solves |
| Hermes translation | The smallest local version we should build |
| Safety gate | What must never be auto-enabled? |
| Do not copy | App/framework/vendor pieces to avoid |
| Test/proof | How Viggo can verify the result |

### 4. Translate into a Hermes slice

Prefer these targets in order:

1. docs/runbook/checklist when the primitive is strategic or not ready;
2. parser/validator/diagnostic primitive with tests;
3. CLI command or config/status UX;
4. skill/procedure when it changes agent behavior;
5. plugin/MCP server when the capability belongs at the edge;
6. core model tool only as last resort.

Core rule: keep Hermes's narrow waist. New capability should live at edges unless there is a proven reason to expand the core.

### 5. Verify and decide next action

A mining task is done only when it ends in one of:

- implemented Hermes code + tests + docs;
- design doc with explicit no-runtime decision;
- new AW Lite child task(s) for follow-up implementation;
- skill/runbook patch for future reuse;
- explicit no-action verdict with source-backed reason.

A summary without a translated artifact is not done.

## Filled reference checklist

| Repo/source | Primitive | Current decision |
|---|---|---|
| Continue.dev | rules/prompts/MCP config, terminal risk, context providers | Already translated into repo-local blocks, terminal risk evaluator, MCP import/status, context provider primitives |
| Aider | repo map, diff/apply, git-native loop | Next highest payoff; mine for Hermes repo-work and AW Lite commit discipline |
| Cline | visible tool approvals, diff-before-apply, MCP surfacing | Mine after Aider; focus on trust UX, not VS Code plugin internals |
| Codex CLI | sandbox/approval modes, patch application | Mine with Cline as a safety comparator |
| OpenHands | sandboxed runtime and durable agent task state | Mine for AW Lite execution boundaries, not full platform adoption |
| FastMCP + modelcontextprotocol/servers | server authoring and capability taxonomy | Mine for MCP as adapter layer, not random server installation |
| Mem0/Graphiti/Cognee | fact memory, temporal graph, provenance/conflicts | Mine only with vault-safe proposal/canonical boundary |
| mini-swe-agent/Terminal-Bench/Langfuse | trajectories, grading, traces | Mine to make agent quality measurable |

## Output template

Copy this into a new mining doc or AW Lite task evidence:

```md
# <Primitive> mining: <repos>

## Target

Primitive:
Hermes/Bertus/AW Lite surface:
Decision: implement / design-only / no-action / follow-up tasks

## Sources

| Repo | URL | Commit/tag | License | Status | Files inspected |
|---|---|---|---|---|---|

## Extracted patterns

| Pattern | Source evidence | Hermes translation | Safety gate | Do not copy | Proof |
|---|---|---|---|---|---|

## Implementation slice

Changed paths:
Tests:
Docs:
Release needed: no/yes, reason

## Recheck

Done-claim attacked:
Fixed now:
Residual risk:

## Follow-up materialization

- [ ] follow-up task or explicit no-action reason
```

## Guardrails

- No broad app forks.
- No secrets from source repos or sample configs.
- No random MCP marketplace installs.
- No hidden prompt injection from repo docs.
- No runtime-active project-local behavior without trust/allowlist.
- No core tool expansion unless the edge/plugin/CLI route fails.
- No “green” claim without tests, readback, or explicit design-only evidence.
