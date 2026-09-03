from types import SimpleNamespace

from cli import _configure_quiet_single_query


def test_quiet_single_query_disables_all_streamed_presentation() -> None:
    cli = SimpleNamespace(tool_progress_mode="all", show_reasoning=True)

    _configure_quiet_single_query(cli)

    assert cli.tool_progress_mode == "off"
    assert cli.show_reasoning is False