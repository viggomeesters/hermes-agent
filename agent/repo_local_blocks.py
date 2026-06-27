"""Project-local Hermes rule/prompt block discovery.

This module is intentionally a parser/discovery primitive only. Runtime prompt
injection is a separate integration decision because per-conversation prompt
caching requires repo-local blocks to be loaded at session startup or explicit
reset/reload boundaries, never silently mid-turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

try:  # pragma: no cover - exercised by import fallback tests in downstream envs
    import yaml
except Exception:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

BlockKind = Literal["rule", "prompt"]


@dataclass(frozen=True)
class RepoLocalBlock:
    """A parsed repo-local Hermes block from `.hermes/rules` or `.hermes/prompts`."""

    kind: BlockKind
    name: str
    body: str
    source_file: Path
    description: str | None = None
    globs: tuple[str, ...] = ()
    regex: tuple[str, ...] = ()
    always_apply: bool | None = None
    invokable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepoLocalBlockError:
    """Non-fatal parser/discovery error for diagnostics."""

    source_file: Path
    message: str


@dataclass(frozen=True)
class RepoLocalBlockDiscovery:
    """Discovery result. Errors are non-fatal so one bad block doesn't break startup."""

    root: Path
    rules: tuple[RepoLocalBlock, ...]
    prompts: tuple[RepoLocalBlock, ...]
    errors: tuple[RepoLocalBlockError, ...]


def discover_repo_local_blocks(workdir: str | Path) -> RepoLocalBlockDiscovery:
    """Discover `.hermes/rules/*.md` and `.hermes/prompts/*.md` under a workdir.

    Scope is deliberately narrow: only the provided workdir's own `.hermes`
    directory is inspected. Parent traversal, trust prompts, allowlists, and
    runtime injection belong to a later integration layer.
    """

    root = Path(workdir).expanduser().resolve()
    base = root / ".hermes"
    errors: list[RepoLocalBlockError] = []

    rules = _load_block_dir(base / "rules", "rule", errors)
    prompts = _load_block_dir(base / "prompts", "prompt", errors)

    return RepoLocalBlockDiscovery(
        root=root,
        rules=tuple(rules),
        prompts=tuple(prompts),
        errors=tuple(errors),
    )


def _load_block_dir(
    directory: Path,
    kind: BlockKind,
    errors: list[RepoLocalBlockError],
) -> list[RepoLocalBlock]:
    if not directory.exists():
        return []
    if not directory.is_dir():
        errors.append(RepoLocalBlockError(directory, "expected directory"))
        return []

    blocks: list[RepoLocalBlock] = []
    for path in sorted(directory.glob("*.md"), key=lambda p: p.name.lower()):
        try:
            blocks.append(parse_repo_local_block(path, kind))
        except ValueError as exc:
            errors.append(RepoLocalBlockError(path, str(exc)))
    return blocks


def parse_repo_local_block(path: str | Path, kind: BlockKind) -> RepoLocalBlock:
    """Parse a markdown repo-local block with optional YAML frontmatter."""

    source_file = Path(path)
    text = source_file.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(text, source_file)

    name = str(metadata.get("name") or source_file.stem).strip()
    if not name:
        raise ValueError("block name is empty")

    description = _optional_str(metadata.get("description"))
    globs = _string_tuple(metadata.get("globs"))
    regex = _string_tuple(metadata.get("regex"))
    always_apply = _optional_bool(metadata.get("alwaysApply", metadata.get("always_apply")))
    invokable = bool(metadata.get("invokable", kind == "prompt"))

    return RepoLocalBlock(
        kind=kind,
        name=name,
        description=description,
        body=body.strip(),
        source_file=source_file,
        globs=globs,
        regex=regex,
        always_apply=always_apply,
        invokable=invokable,
        metadata=metadata,
    )


def _split_frontmatter(text: str, source_file: Path) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text

    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("frontmatter start marker found without closing marker")

    raw = text[4:end]
    body = text[end + len("\n---\n") :]
    if yaml is None:
        raise ValueError("PyYAML is required to parse frontmatter")

    try:
        parsed = yaml.safe_load(raw) or {}
    except Exception as exc:  # noqa: BLE001 - report parser failures as diagnostics
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("frontmatter must be a mapping")
    return dict(parsed), body


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError("alwaysApply/always_apply must be a boolean when provided")


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise ValueError("globs/regex must be a string or list of strings")
