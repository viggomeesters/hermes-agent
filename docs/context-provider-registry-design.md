# Context provider registry design

This design captures the Continue context-provider pattern for Hermes without wiring dynamic context into prompt assembly yet.

Implementation primitive: `agent.context_providers`.

## Goal

Create a shared shape for context surfaces that avoids adding new model tools for every context source.

Context providers are for explicitly selected context, not automatic broad injection.

## Interface

```python
class ContextProvider(Protocol):
    descriptor: ContextProviderDescriptor
    def get_context_items(self, query: ContextQuery) -> Iterable[ContextItem]: ...
```

Key types:

- `ContextProviderType.NORMAL`
- `ContextProviderType.QUERY`
- `ContextProviderType.SUBMENU`
- `ContextSurface.CLI`
- `ContextSurface.GATEWAY`
- `ContextSurface.TUI`
- `ContextSurface.ACP`
- `ContextSurface.CRON`

## Proposed default providers

| Provider | Type | Purpose | Default |
|---|---|---|---|
| `repo` | submenu | Workdir/git/diff/codebase context | enabled |
| `vault` | query | Bounded vault search/read excerpts | enabled |
| `session` | query | Past Hermes sessions via session_search-like retrieval | enabled |
| `cron` | submenu | Job status and output handles | enabled |
| `mcp_resources` | submenu | MCP resources/resourceTemplates as context | disabled |

## Lifecycle

1. Discover built-in providers at process/session startup.
2. Discover configured providers from config or plugin surfaces.
3. Discover MCP resource providers only from already trusted/enabled MCP servers.
4. Freeze provider descriptor set for the session/request prefix.
5. Query providers only when a user/surface explicitly selects one.
6. Require explicit reset/reload before newly added providers affect prompt assembly.

This preserves per-conversation prompt caching and avoids hidden tool/context surface mutation mid-turn.

## Surface filtering

Each provider declares surfaces where it is usable:

- CLI/TUI can show full menus.
- Gateway/Telegram should expose only compact, allowlisted providers.
- ACP/editor can expose repo and MCP resources later.
- Cron should avoid interactive providers by default.

## MCP resources → context

Continue's useful pattern: MCP is not just tools.

Mapping for Hermes:

| MCP capability | Future Hermes surface |
|---|---|
| `tools` | Existing MCP tools |
| `resources` | Context provider items |
| `resourceTemplates` | Query/submenu context providers |
| `prompts` | Slash/command registry, not context provider |

Safety gates before implementation:

- Only resources from enabled/trusted MCP servers.
- Size limits per resource and total provider output.
- Text-only normalization, with binary/image resources represented as handles unless a surface supports them.
- Source URI retained in `ContextItem.uri`.
- Resource names/descriptions are evidence, not instructions.

## MCP prompts → commands

Prompts should not be silently inserted into the prompt. Future mapping:

```text
MCP prompt -> command descriptor -> explicit user invocation
```

Telegram exposure must be allowlisted. CLI/TUI can show more complete menus.

## Non-goals for this slice

- No prompt assembly integration.
- No automatic provider querying.
- No MCP connection changes.
- No project-local MCP auto-discovery.
- No new model tools.
