"""Lock audit for calls on the shared SessionDB writer connection (#99502).

SessionDB._conn is shared across threads with check_same_thread=False. Every
call on it must hold self._lock. Reads that should not contend on the writer
lock belong in SessionDB._read_ctx().
"""

import ast
from pathlib import Path


_ALLOWED_UNLOCKED_FNS = frozenset(
    {
        "__init__",
        "_connect_and_init",
        "_connect_and_init_with_lock_patience",
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _nearest_enclosing_fn(tree: ast.AST) -> dict[int, str]:
    enclosing: dict[int, str] = {}

    def visit(node: ast.AST, current: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            current = node.name
        enclosing[id(node)] = current
        for child in ast.iter_child_nodes(node):
            visit(child, current)

    visit(tree, "<module>")
    return enclosing


def _unlocked_conn_calls(tree: ast.AST) -> list[tuple[int, str, str]]:
    locked_ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                ctx = item.context_expr
                if (
                    isinstance(ctx, ast.Attribute)
                    and ctx.attr == "_lock"
                    and isinstance(ctx.value, ast.Name)
                    and ctx.value.id == "self"
                ):
                    locked_ids.update(id(child) for child in ast.walk(node))

    enclosing = _nearest_enclosing_fn(tree)
    offending: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "_conn"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "self"
        ):
            continue
        if id(node) in locked_ids:
            continue
        fn = enclosing.get(id(node), "<module>")
        if fn in _ALLOWED_UNLOCKED_FNS:
            continue
        offending.append((node.lineno, fn, func.attr))
    return offending


def test_every_conn_call_outside_construction_holds_the_lock() -> None:
    src = (_repo_root() / "hermes_state.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offending = _unlocked_conn_calls(tree)
    assert not offending, (
        "self._conn.<method>() called without `with self._lock:`: "
        f"{offending!r}. Route reads through `_read_ctx()` or take the lock."
    )
