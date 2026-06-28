# Aider mining: repo-map and git diff discipline

Source repo: `Aider-AI/aider` inspected locally at `/tmp/aider-inspect`, commit `5dc9490`.

Public docs consulted:

- `https://aider.chat/docs/repomap.html`
- `https://aider.chat/docs/git.html`
- `https://aider.chat/docs/usage.html`

Local source files inspected:

- `/tmp/aider-inspect/aider/repomap.py`
- `/tmp/aider-inspect/aider/repo.py`
- `/tmp/aider-inspect/aider/commands.py`
- `/tmp/aider-inspect/aider/coders/base_coder.py`
- `/tmp/aider-inspect/aider/coders/editblock_coder.py`

## What to steal

Aider's strongest transferable idea is not the whole CLI. It is the combination of:

1. **small editable file set**: only the files in the active task are editable/in-chat;
2. **bounded repo map**: the rest of the repo is summarized as symbol/signature context;
3. **git-native change units**: each AI change is diffable, committable and undoable;
4. **dirty-state separation**: pre-existing user changes are kept separate from agent changes;
5. **diff as the review surface**: changes are made visible as diffs, not hidden final state.

## Evidence from Aider

| Pattern | Source evidence | Hermes translation |
|---|---|---|
| Bounded whole-repo context | `repomap.py::RepoMap.get_repo_map`; docs describe a concise map of important classes/functions/signatures | `agent.repo_map_summary` gives a Python-first bounded symbol map primitive; future work can use codebase-memory for richer cross-language maps |
| Token-aware expansion | `get_repo_map` grows map when no files are in chat and uses `map_tokens`/context budget | Hermes should only expand repo context when no scoped files are known; AW Lite task `scope.read` remains the first boundary |
| Persistent tag cache | `RepoMap.TAGS_CACHE_DIR`, cache by file mtime | Future Hermes map cache should live outside prompt and be invalidated by mtime/hash; not implemented in this slice |
| Git-native edits | `repo.py::GitRepo.commit`, `/commit`, `/diff`, `/undo` docs | AW Lite already commits per task; add repo map/diff discipline as a quality gate, not auto-commit every model turn |
| Dirty change protection | Aider docs say dirty files are committed before edits | Hermes should not auto-commit user dirt; it should detect/report unrelated dirt and stage only task paths |

## Implemented slice

Added `agent.repo_map_summary`:

- `extract_python_symbols(path, root=...)`
- `build_python_repo_symbol_map(root, files, max_symbols=..., max_chars=...)`

This is intentionally small and opt-in. It does **not** mutate prompt assembly, does **not** add a model tool, and does **not** replace codebase-memory. It gives Hermes a local deterministic primitive for future repo-map quality gates and tests.

## Why not copy more

Do not copy:

- Aider's entire chat CLI;
- auto-commit every model turn;
- automatic dirty-commit behavior;
- tree-sitter/diskcache dependency stack before a real consumer exists;
- prompt injection of repo maps into long-running conversations without reset/cache planning.

## Future follow-up

Potential next slice:

- Add an AW Lite `repo_map_evidence` helper that creates a symbol map only for `scope.read` and changed file neighborhoods.
- Compare the map against `git diff --name-only` to flag uninspected high-impact modules before finish.
- For non-Python repos, prefer codebase-memory or language-specific lightweight extractors.
