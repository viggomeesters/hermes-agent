# Repo-local rules and prompts spike

This is the implementation note for `agent.repo_local_blocks`, a small parser/discovery primitive inspired by Continue's `.continue/rules` and `.continue` prompt block model.

## Implemented in this spike

- Discovery for exactly these workdir-scoped directories:
  - `.hermes/rules/*.md`
  - `.hermes/prompts/*.md`
- Markdown blocks with optional YAML frontmatter.
- Lexicographic ordering by filename.
- Non-fatal diagnostics: one bad block does not prevent other blocks from loading.
- A narrow dataclass model that preserves source path and metadata.

## Intentional boundaries

- No runtime prompt injection yet.
- No parent-directory traversal.
- No Telegram command exposure.
- No MCP/project-local command execution.
- No mid-conversation reload; any future integration must happen at session startup or explicit reset/reload boundaries to preserve prompt caching.

## Candidate rule format

```md
---
name: Python standards
description: Applies when editing Python files
globs: ["**/*.py"]
alwaysApply: false
---

- Prefer pytest tests for behavior changes.
- Keep config in config.yaml; `.env` is for secrets only.
```

## Candidate prompt format

```md
---
name: Review diff
description: Review the current git diff before ship
invokable: true
---

Review the current diff for scope creep, missing tests, and cache-breaking changes.
```

## Future integration gates

Before connecting this to system prompt assembly or slash command registries:

1. Add an explicit config flag, e.g. `project_blocks.enabled`.
2. Add diagnostics (`hermes project-blocks list` or equivalent) showing loaded files and errors.
3. Decide precedence relative to AGENTS.md, skills, user/system/developer prompts.
4. Keep loading session-start stable; require `/reset` or explicit reload for changes.
5. Do not expose prompts into Telegram command menus unless allowlisted.
