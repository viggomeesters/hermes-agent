from pathlib import Path

from agent.repo_local_blocks import discover_repo_local_blocks, parse_repo_local_block


def test_discover_repo_local_rules_and_prompts_in_lexicographic_order(tmp_path: Path):
    rules = tmp_path / ".hermes" / "rules"
    prompts = tmp_path / ".hermes" / "prompts"
    rules.mkdir(parents=True)
    prompts.mkdir(parents=True)

    (rules / "20-python.md").write_text(
        "---\nname: Python\nglobs: ['**/*.py']\nalwaysApply: false\ndescription: Python rules\n---\nUse pytest.\n",
        encoding="utf-8",
    )
    (rules / "01-general.md").write_text("No secrets.\n", encoding="utf-8")
    (prompts / "review.md").write_text(
        "---\nname: Review\ndescription: Review current diff\ninvokable: true\n---\nReview the diff.\n",
        encoding="utf-8",
    )

    result = discover_repo_local_blocks(tmp_path)

    assert result.errors == ()
    assert [rule.name for rule in result.rules] == ["01-general", "Python"]
    assert result.rules[1].globs == ("**/*.py",)
    assert result.rules[1].always_apply is False
    assert result.prompts[0].name == "Review"
    assert result.prompts[0].invokable is True
    assert result.prompts[0].body == "Review the diff."


def test_discovery_is_workdir_scoped_and_does_not_walk_parent(tmp_path: Path):
    parent_rules = tmp_path / ".hermes" / "rules"
    child = tmp_path / "child"
    parent_rules.mkdir(parents=True)
    child.mkdir()
    (parent_rules / "parent.md").write_text("parent only", encoding="utf-8")

    result = discover_repo_local_blocks(child)

    assert result.rules == ()
    assert result.prompts == ()
    assert result.errors == ()


def test_bad_block_is_non_fatal_and_reported(tmp_path: Path):
    rules = tmp_path / ".hermes" / "rules"
    rules.mkdir(parents=True)
    (rules / "bad.md").write_text("---\nname: [unterminated\n---\nbody\n", encoding="utf-8")
    (rules / "good.md").write_text("body\n", encoding="utf-8")

    result = discover_repo_local_blocks(tmp_path)

    assert [rule.name for rule in result.rules] == ["good"]
    assert len(result.errors) == 1
    assert result.errors[0].source_file.name == "bad.md"
    assert "invalid YAML frontmatter" in result.errors[0].message


def test_parse_frontmatter_lists_and_body(tmp_path: Path):
    path = tmp_path / "rule.md"
    path.write_text(
        "---\nname: TS\nregex:\n  - '^import '\nglobs: src/**/*.ts\n---\n- Use interfaces\n",
        encoding="utf-8",
    )

    block = parse_repo_local_block(path, "rule")

    assert block.name == "TS"
    assert block.regex == ("^import ",)
    assert block.globs == ("src/**/*.ts",)
    assert block.body == "- Use interfaces"
