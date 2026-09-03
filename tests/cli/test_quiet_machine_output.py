from types import SimpleNamespace

from cli import _configure_no_fallback, _configure_quiet_single_query


def test_quiet_single_query_disables_all_streamed_presentation() -> None:
    cli = SimpleNamespace(tool_progress_mode="all", show_reasoning=True)

    _configure_quiet_single_query(cli)

    assert cli.tool_progress_mode == "off"
    assert cli.show_reasoning is False


def test_no_fallback_clears_runtime_chain_without_touching_route():
    cli = SimpleNamespace(
        _fallback_model=[{"provider": "openrouter", "model": "fallback"}],
        provider="openai-codex",
        model="gpt-5.6-sol",
    )

    _configure_no_fallback(cli)

    assert cli._fallback_model == []
    assert cli.provider == "openai-codex"
    assert cli.model == "gpt-5.6-sol"


def test_chat_parser_accepts_no_fallback():
    from hermes_cli._parser import build_top_level_parser

    parser, _subparsers, _chat = build_top_level_parser()
    args = parser.parse_args(["chat", "--no-fallback"])

    assert args.no_fallback is True