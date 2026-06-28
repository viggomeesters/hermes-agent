"""Lightweight repository symbol-map primitives.

Inspired by Aider's repo-map pattern, this module intentionally implements only
a small Python-first primitive: extract file-local class/function signatures into
a bounded text map. It is not wired into prompt assembly; callers must opt in.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RepoSymbol:
    path: str
    line: int
    kind: str
    name: str
    signature: str


def _signature(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        bases = [ast.unparse(base) for base in node.bases]
        return f"class {node.name}" + (f"({', '.join(bases)})" if bases else "")
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        try:
            args = ast.unparse(node.args)
        except Exception:
            args = "..."
        return f"{prefix} {node.name}({args})"
    return ""


def extract_python_symbols(path: Path, *, root: Path | None = None) -> list[RepoSymbol]:
    """Extract top-level and class-level Python symbols from ``path``.

    Parser failures return an empty list so callers can build best-effort maps
    without turning one bad file into a hard failure.
    """
    root = root or path.parent
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []

    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
    symbols: list[RepoSymbol] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            symbols.append(RepoSymbol(rel, node.lineno, "class", node.name, _signature(node)))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(
                        RepoSymbol(
                            rel,
                            child.lineno,
                            "method",
                            f"{node.name}.{child.name}",
                            _signature(child),
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(RepoSymbol(rel, node.lineno, "function", node.name, _signature(node)))
    return symbols


def build_python_repo_symbol_map(
    root: Path,
    files: Iterable[Path],
    *,
    max_symbols: int = 200,
    max_chars: int = 12000,
) -> str:
    """Return a deterministic bounded symbol map for selected Python files."""
    root = root.resolve()
    all_symbols: list[RepoSymbol] = []
    for file in sorted({Path(file).resolve() for file in files}):
        if file.suffix != ".py":
            continue
        all_symbols.extend(extract_python_symbols(file, root=root))
        if len(all_symbols) >= max_symbols:
            break

    grouped: dict[str, list[RepoSymbol]] = {}
    for symbol in all_symbols[:max_symbols]:
        grouped.setdefault(symbol.path, []).append(symbol)

    lines: list[str] = []
    for path, symbols in grouped.items():
        candidate = [f"{path}:"] + [
            f"  L{symbol.line}: {symbol.signature}" for symbol in symbols
        ]
        next_text = "\n".join(lines + candidate) + "\n"
        if len(next_text) > max_chars:
            lines.append("... truncated to symbol-map budget")
            break
        lines.extend(candidate)
    return "\n".join(lines).strip()
