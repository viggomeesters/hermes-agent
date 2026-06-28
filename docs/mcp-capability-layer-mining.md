# MCP ecosystem mining: capability layer

Sources inspected:

| Source | Evidence |
|---|---|
| FastMCP / Python MCP SDK search results | Pythonic server authoring exposes tools, resources and prompts as distinct primitives |
| MCP tools specification search result | Tools may include annotations such as `readOnlyHint` and `destructiveHint`; annotations are trust/safety signals, not enforcement |
| Prior Continue mining | `docs/mcp-json-import-status-spike.md` and `docs/context-provider-registry-design.md` already capture import/status and resources-as-context decisions |

## What to steal

MCP is valuable when treated as a **capability taxonomy**, not a marketplace.

The important split:

| Capability | Meaning | Hermes surface |
|---|---|---|
| tool | executable function, maybe side-effecting | agent tool with policy |
| resource | context/data payload | context provider |
| resource template | queryable context/data payload | query context provider |
| prompt | reusable interaction template | command candidate behind allowlist |

## Risk model

Tool annotations are helpful but untrusted. Use them as a policy input:

- `readOnlyHint=true` and not `openWorldHint` → can be low-friction read-only tool;
- `destructiveHint=true` → approval required and blocked-by-default surface;
- missing hints → ask, because silence is not proof of safety;
- prompts → allowlist before exposing as slash/Telegram commands;
- resources → context with provenance, never hidden instructions.

## Implemented slice

Added `agent.mcp_capabilities`:

- `McpCapabilityKind`: tool/resource/resource_template/prompt;
- `McpRiskTier`: context/read-only tool/side-effect tool/destructive tool/prompt template;
- `classify_mcp_capability(kind, annotations=...)`.

This complements the earlier MCP JSON import/status work. It gives future MCP UI/import code a deterministic vocabulary for surfacing capabilities safely.

## What not to copy

- random MCP server marketplace installs;
- treating server-provided annotations as authoritative;
- auto-exposing prompts as commands;
- turning resources into hidden system prompt instructions;
- secrets in MCP YAML/JSON;
- broad project-local MCP autoload.

## Future follow-up

- Use this classifier in `hermes mcp status --verbose` so operators see capability risk tiers.
- Add per-server/per-tool allowlists once project-local MCP blocks are implemented.
- Add MCP prompt import as command candidates only after explicit trust UI exists.
