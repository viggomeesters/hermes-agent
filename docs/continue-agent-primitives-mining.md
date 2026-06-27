# Continue.dev agent primitives mining

Source: `continuedev/continue` inspected at commit `d0a3c0b` plus the local mining notes in `/home/viggo/continue-mining-notes.md` and `/home/viggo/continue-mcp-steal-go-plan.md`.

Purpose: capture reusable Continue patterns in a Hermes-maintainable artifact so future work does not depend on chat memory.

## Decision summary

Continue is not a product base to fork. It is a pattern mine for agent product primitives. For Hermes, steal UX and architecture patterns that keep the core narrow and improve edge capabilities.

| Area | Already in Hermes | Still worth building | Do not copy |
|---|---|---|---|
| MCP tools | Native MCP client discovers tools as `mcp_<server>_<tool>` | `.mcp.json` import, verbose status, resources-as-context, prompts-as-commands, project-local blocks behind trust gates | Random community MCP auto-load; secrets in YAML; browser MCP as default |
| Skills/rules/prompts | Skills exist; slash commands exist; AGENTS.md project instructions exist | Repo-local `.hermes/rules/*.md` and `.hermes/prompts/*.md` as lightweight blocks with frontmatter and deterministic ordering | Mid-conversation prompt mutation; bloating core tool schema |
| Tool permissions | Hermes has approval modes/manual-smart-off and dangerous command approval | A tightening command-risk evaluator layer inspired by Continue's shell parser | Replacing existing approvals or weakening manual mode |
| Context | Hermes has tool context, memory, session search, vault workflows | A registry pattern for vault/repo/session/cron/MCP context providers; MCP resources become context, not tool calls | Injecting dynamic context in a cache-breaking way |
| Autocomplete/next-edit | Not a current Hermes runtime surface | Keep as future editor/ACP inspiration: debounce, prefix cache, stream filtering | Implement now without an editor consumer |
| Model adapters | Hermes already has provider routing | Optional future metadata registry with `recommendedFor`, context length, media types | Copy Continue provider tables blindly |

## Pattern 1 — composable assistant config

Continue models an assistant as a config bundle:

- `models`
- `context`
- `data`
- `mcpServers`
- `rules`
- `prompts`
- `docs`

Source path: `/tmp/continue-inspect/packages/config-yaml/src/schemas/index.ts`.

Hermes translation:

- Keep heavy reusable procedures as skills.
- Add lightweight repo-local blocks only where they avoid skill bloat:
  - `.hermes/rules/*.md`
  - `.hermes/prompts/*.md`
  - `.hermes/mcpServers/*.{yaml,json}` later, only behind trust gates.
- Preserve prompt caching: load blocks only at session/workdir startup, not mid-conversation.

## Pattern 2 — rules as ordered markdown blocks

Continue rule fields:

- `name`
- `rule`
- `description`
- `globs`
- `regex`
- `alwaysApply`
- `invokable`
- `sourceFile`

Source paths:

- `/tmp/continue-inspect/packages/config-yaml/src/schemas/index.ts:39-49`
- `/tmp/continue-inspect/docs/customize/deep-dives/rules.mdx`

Hermes translation:

- `.hermes/rules/01-general.md`, `.hermes/rules/02-python.md`, etc.
- YAML frontmatter + markdown body.
- Lexicographic load order.
- Applicability levels:
  - always
  - glob match
  - regex/content match
  - agent-selected by description, only when safe and explicit.

Safety gate: repo-local rules must be visible in diagnostics and should not silently override higher-priority system/developer rules.

## Pattern 3 — prompts as slash-command blocks

Continue prompt fields:

- `name`
- `description`
- `prompt`
- `sourceFile`
- `invokable` in markdown frontmatter for slash-command exposure.

Source paths:

- `/tmp/continue-inspect/packages/config-yaml/src/schemas/index.ts:19-24`
- `/tmp/continue-inspect/docs/customize/deep-dives/prompts.mdx`

Hermes translation:

- `.hermes/prompts/*.md` as project-local prompt snippets.
- CLI invocation can become `/prompt:<name>` or `hermes prompt run <name>` later.
- Telegram exposure must be allowlisted, not automatic.

## Pattern 4 — tool permissions and command-risk evaluator

Continue separates policy from call-specific risk:

```text
default policy -> override/mode policy -> evaluateToolCallPolicy(args)
```

Policy values:

- `allowedWithoutPermission`
- `allowedWithPermission`
- `disabled`

Source paths:

- `/tmp/continue-inspect/packages/terminal-security/src/types.ts`
- `/tmp/continue-inspect/packages/terminal-security/src/evaluateTerminalCommandSecurity.ts`
- `/tmp/continue-inspect/core/tools/definitions/runTerminalCommand.ts`
- `/tmp/continue-inspect/docs/cli/tool-permissions.mdx`

Hermes translation:

- Keep existing `approvals.mode` semantics.
- Add a narrowing command-risk layer for terminal commands:
  - parse shell tokens, not only regex;
  - split multiline commands;
  - variable expansion forces at least ask;
  - pipes are evaluated specially;
  - parser failure => ask;
  - most restrictive finding wins.

Safety gate: this layer must never auto-approve something Hermes would currently ask for.

## Pattern 5 — MCP is tools + resources + prompts

Continue's strongest MCP pattern is capability mapping:

| MCP capability | Continue surface | Hermes target |
|---|---|---|
| `tools` | agent tools | current native MCP tools |
| `resources` | context provider items | future context provider registry |
| `resourceTemplates` | context submenu/query provider | future `@mcp:<server>/<resource>` context |
| `prompts` | slash commands | future CLI slash commands; Telegram only allowlisted |

Source paths:

- `/tmp/continue-inspect/packages/config-yaml/src/schemas/mcp/index.ts`
- `/tmp/continue-inspect/core/context/mcp/MCPConnection.ts`
- `/tmp/continue-inspect/core/context/providers/MCPContextProvider.ts`
- `/tmp/continue-inspect/docs/customize/deep-dives/mcp.mdx`

Hermes translation:

1. First improve operator UX:
   - `.mcp.json` import dry-run;
   - verbose status with source/transport/tools/resources/prompts/errors;
   - useful hints for missing `npx`, `node`, `uv`, `uvx`.
2. Then add capability surfaces:
   - resources as context providers;
   - prompts as commands;
   - project-local MCP blocks only after trust model is clear.

Do not copy:

- broad auto-loading of repo-provided commands;
- secrets inside config files;
- unaudited community MCP packages.

## Pattern 6 — context provider registry

Continue has provider classes with descriptions and a loader that combines configured and default providers.

Source paths:

- `/tmp/continue-inspect/core/context/providers/index.ts`
- `/tmp/continue-inspect/core/config/loadContextProviders.ts`

Hermes translation:

Design an edge registry, not a new core tool explosion:

```python
class ContextProvider:
    name: str
    display_name: str
    provider_type: Literal['normal', 'query', 'submenu']
    def get_context_items(query, extras): ...
```

Initial conceptual providers:

- repo/diff/git
- vault bounded search
- session history
- cron/job status
- MCP resources
- rules/prompts metadata

Cache-safety gate: provider discovery must be session-start stable unless an explicit reset/reload happens.

## Pattern 7 — autocomplete pipeline, parked for later

Continue autocomplete pipeline:

- request UUID debouncing;
- SQLite LRU prefix cache;
- longest-prefix match;
- generator reuse;
- context snippets from imports/root path/static context;
- stream transforms and postprocessing.

Source paths:

- `/tmp/continue-inspect/core/autocomplete/CompletionProvider.ts`
- `/tmp/continue-inspect/core/autocomplete/util/AutocompleteDebouncer.ts`
- `/tmp/continue-inspect/core/autocomplete/util/AutocompleteLruCache.ts`
- `/tmp/continue-inspect/core/autocomplete/generation/CompletionStreamer.ts`

Hermes decision: do not implement until there is an editor/ACP suggestion consumer. Keep it as future design input.

## Pattern 8 — model metadata registry, parked for later

Continue separates provider adapter implementation from model metadata:

- `contextLength`
- `maxCompletionTokens`
- `mediaTypes`
- `recommendedFor`
- `extraParameters`
- regex model matching

Source paths:

- `/tmp/continue-inspect/packages/llm-info/src/types.ts`
- `/tmp/continue-inspect/packages/llm-info/src/index.ts`
- `/tmp/continue-inspect/packages/openai-adapters/src/index.ts`

Hermes decision: useful future config-validation/UI metadata, but not part of the current MCP/rules/prompts execution package.

## Implementation order for Hermes

1. Preserve this knowledge in repo docs/skills.
2. Spike repo-local rules/prompts as session-start-only blocks.
3. Add terminal command-risk evaluator as a tightening layer.
4. Add `.mcp.json` import dry-run and verbose MCP status.
5. Design context provider registry.
6. Later: MCP resources as context and MCP prompts as commands.
7. Later: project-local MCP blocks with allowlist/trust prompts.

## Done criteria for follow-up implementation

- Every runtime feature has tests against a temporary `HERMES_HOME`.
- No new core model tool is added for these patterns.
- No config changes are sourced from `.env` unless they are secrets.
- New project-local discovery is opt-in/allowlisted.
- Existing prompt caching and toolset stability are preserved.
