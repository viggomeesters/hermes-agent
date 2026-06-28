from pathlib import Path

from agent.repo_map_summary import build_python_repo_symbol_map, extract_python_symbols


def test_extract_python_symbols_top_level_and_class_methods(tmp_path: Path):
    source = tmp_path / "sample.py"
    source.write_text(
        "class Service(Base):\n"
        "    def run(self, value: int = 1):\n"
        "        return value\n\n"
        "async def fetch(name: str):\n"
        "    return name\n",
        encoding="utf-8",
    )

    symbols = extract_python_symbols(source, root=tmp_path)

    assert [(s.kind, s.name, s.signature) for s in symbols] == [
        ("class", "Service", "class Service(Base)"),
        ("method", "Service.run", "def run(self, value: int=1)"),
        ("function", "fetch", "async def fetch(name: str)"),
    ]


def test_build_python_repo_symbol_map_is_bounded_and_deterministic(tmp_path: Path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("def alpha():\n    pass\n", encoding="utf-8")
    b.write_text("def beta(x):\n    pass\n", encoding="utf-8")

    result = build_python_repo_symbol_map(tmp_path, [b, a], max_chars=1000)

    assert result.splitlines() == [
        "a.py:",
        "  L1: def alpha()",
        "b.py:",
        "  L1: def beta(x)",
    ]


def test_extract_python_symbols_returns_empty_for_invalid_python(tmp_path: Path):
    bad = tmp_path / "bad.py"
    bad.write_text("def nope(:\n", encoding="utf-8")

    assert extract_python_symbols(bad, root=tmp_path) == []
