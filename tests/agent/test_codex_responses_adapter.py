from types import SimpleNamespace

import pytest

from agent.codex_responses_adapter import (
    _chat_messages_to_responses_input,
    _format_responses_error,
    _normalize_codex_response,
    _preflight_codex_api_kwargs,
)


def test_normalize_codex_response_drops_transient_rs_tmp_reasoning_items():
    response = SimpleNamespace(
        status="completed",
        output=[
            SimpleNamespace(
                type="reasoning",
                id="rs_tmp_123",
                encrypted_content="opaque-transient",
                summary=[],
            ),
            SimpleNamespace(
                type="reasoning",
                id="rs_456",
                encrypted_content="opaque-stable",
                summary=[SimpleNamespace(text="stable summary")],
            ),
            SimpleNamespace(
                type="message",
                role="assistant",
                status="completed",
                content=[SimpleNamespace(type="output_text", text="done")],
            ),
        ],
    )

    assistant_message, finish_reason = _normalize_codex_response(response)

    assert finish_reason == "stop"
    assert assistant_message.content == "done"
    assert assistant_message.codex_reasoning_items == [
        {
            "type": "reasoning",
            "encrypted_content": "opaque-stable",
            "id": "rs_456",
            "summary": [{"type": "summary_text", "text": "stable summary"}],
        }
    ]


def test_normalize_codex_response_treats_summary_only_reasoning_as_incomplete():
    response = SimpleNamespace(
        status="completed",
        output=[
            SimpleNamespace(
                type="reasoning",
                id="rs_tmp_789",
                encrypted_content="opaque-transient",
                summary=[SimpleNamespace(text="still thinking")],
            )
        ],
    )

    assistant_message, finish_reason = _normalize_codex_response(response)

    assert finish_reason == "incomplete"
    assert assistant_message.content == ""
    assert assistant_message.reasoning == "still thinking"
    assert assistant_message.codex_reasoning_items is None


# ---------------------------------------------------------------------------
# Server-side built-in tool calls (xAI native web_search, code interpreter,
# etc.) come back as discrete ``*_call`` output items that xAI's
# /v1/responses surface routinely leaves at ``status="in_progress"`` even
# when the overall ``response.status == "completed"``.  These must NOT mark
# the turn incomplete — otherwise grok-composer-2.5-fast research queries
# (which invoke server-side web_search) get misclassified as
# ``finish_reason="incomplete"`` and burn 3 fruitless continuation retries
# before failing with "Codex response remained incomplete after 3
# continuation attempts".  Observed live against grok-composer-2.5-fast on
# SuperGrok OAuth (2026-06).
# ---------------------------------------------------------------------------


def test_normalize_codex_response_ignores_in_progress_server_side_tool_calls():
    """A completed response with a final message + lingering in_progress
    server-side web_search_call items resolves to 'stop', not 'incomplete'."""
    response = SimpleNamespace(
        status="completed",
        incomplete_details=None,
        output=[
            SimpleNamespace(
                type="reasoning",
                id="rs_1",
                encrypted_content="opaque",
                summary=[SimpleNamespace(text="researching blades")],
            ),
            SimpleNamespace(
                type="message",
                role="assistant",
                status="completed",
                content=[SimpleNamespace(
                    type="output_text",
                    text="Milwaukee M18 blade 49-16-2734, ~$30 OEM.",
                )],
            ),
            SimpleNamespace(type="web_search_call", status="in_progress"),
            SimpleNamespace(type="web_search_call", status="in_progress"),
            SimpleNamespace(type="web_search_call", status="in_progress"),
        ],
    )

    assistant_message, finish_reason = _normalize_codex_response(response)

    assert finish_reason == "stop"
    assert assistant_message.content == "Milwaukee M18 blade 49-16-2734, ~$30 OEM."


def test_normalize_codex_response_in_progress_message_still_incomplete():
    """Guard scope: an in_progress *message* item (genuine model output that
    is still streaming) must still mark the turn incomplete — only
    server-side ``*_call`` items are exempted."""
    response = SimpleNamespace(
        status="completed",
        incomplete_details=None,
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                status="in_progress",
                content=[SimpleNamespace(type="output_text", text="partial...")],
            ),
        ],
    )

    _assistant_message, finish_reason = _normalize_codex_response(response)

    assert finish_reason == "incomplete"


# ---------------------------------------------------------------------------
# _preflight_codex_api_kwargs — built-in (provider-executed) tools must pass
# through validation.  Regression guard for the xAI native web_search
# injection: the preflight validator previously rejected any tool whose
# ``type != "function"`` with "unsupported type", which would 400 every xAI
# turn once the native web_search tool is declared.
# ---------------------------------------------------------------------------


def test_preflight_passes_native_web_search_tool_through():
    kwargs = {
        "model": "grok-composer-2.5-fast",
        "instructions": "You are helpful.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
        "store": False,
        "tools": [
            {"type": "function", "name": "read_file", "description": "Read.",
             "parameters": {"type": "object", "properties": {}}},
            {"type": "web_search"},
        ],
    }
    out = _preflight_codex_api_kwargs(kwargs, allow_stream=True)
    tools = out["tools"]
    assert {"type": "web_search"} in tools
    assert any(t.get("type") == "function" and t.get("name") == "read_file" for t in tools)


def test_preflight_accepts_native_tool_search_namespaces():
    kwargs = {
        "model": "gpt-5.6-sol",
        "instructions": "You are helpful.",
        "input": [{"role": "user", "content": "read"}],
        "store": False,
        "tools": [
            {
                "type": "namespace",
                "name": "hermes_files",
                "description": "File tools.",
                "tools": [{
                    "type": "function",
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {"type": "object", "properties": {}},
                    "strict": False,
                    "defer_loading": True,
                }],
            },
            {"type": "tool_search"},
        ],
    }

    out = _preflight_codex_api_kwargs(kwargs, allow_stream=True)

    assert out["tools"] == kwargs["tools"]


def test_tool_search_items_round_trip_before_function_call():
    messages = [{
        "role": "assistant",
        "content": "",
        "codex_tool_search_items": [
            {
                "type": "tool_search_call",
                "execution": "server",
                "call_id": None,
                "status": "completed",
                "arguments": {"paths": ["hermes_files"]},
            },
            {
                "type": "tool_search_output",
                "execution": "server",
                "call_id": None,
                "status": "completed",
                "tools": [{"type": "namespace", "name": "hermes_files", "description": "Files.", "tools": [{"type": "function", "name": "read_file", "description": "Read.", "parameters": {"type": "object", "properties": {}}, "strict": False, "defer_loading": True}]}],
            },
        ],
        "tool_calls": [{
            "id": "call_1",
            "call_id": "call_1",
            "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
        }],
    }]

    items = _chat_messages_to_responses_input(messages)

    types = [item.get("type") for item in items]
    assert types == ["tool_search_call", "tool_search_output", "function_call"]
    assert _preflight_codex_api_kwargs({
        "model": "gpt-5.6-sol",
        "instructions": "help",
        "input": items,
        "store": False,
    })["input"] == items


def test_compaction_summary_round_trips_as_canonical_output():
    items = _chat_messages_to_responses_input([{
        "role": "assistant",
        "content": "",
        "codex_output_items": [{
            "type": "compaction_summary",
            "encrypted_content": "opaque-summary",
        }],
    }], current_issuer_kind="codex")
    assert items == [{
        "type": "compaction_summary",
        "encrypted_content": "opaque-summary",
    }]
    assert _preflight_codex_api_kwargs({
        "model": "gpt-5.6-sol",
        "instructions": "help",
        "input": items,
        "store": False,
    })["input"] == items


def test_compaction_summary_keeps_merged_function_call_paired_with_output():
    """A compaction marker merged with the next assistant tool call must not
    make the canonical replay path discard that call while retaining its result.
    """
    items = _chat_messages_to_responses_input([
        {
            "role": "assistant",
            "content": "",
            "codex_output_items": [{
                "type": "compaction_summary",
                "encrypted_content": "opaque-summary",
            }],
            "tool_calls": [{
                "id": "call_after_compaction",
                "call_id": "call_after_compaction",
                "type": "function",
                "function": {
                    "name": "terminal",
                    "arguments": '{"command":"git status --short"}',
                },
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "call_after_compaction",
            "content": '{"output":"clean","exit_code":0}',
        },
    ], current_issuer_kind="codex")

    assert [item["type"] for item in items] == [
        "compaction_summary",
        "function_call",
        "function_call_output",
    ]
    assert items[1]["call_id"] == items[2]["call_id"] == "call_after_compaction"
    assert _preflight_codex_api_kwargs({
        "model": "gpt-5.6-sol",
        "instructions": "help",
        "input": items,
        "store": False,
    })["input"] == items


def test_preflight_drops_interrupted_function_calls_without_outputs():
    """Restored sessions may contain a tool call interrupted before its
    result was persisted. Codex must not receive that invalid call while later
    complete call/output pairs remain intact.
    """
    valid_call = {
        "type": "function_call",
        "call_id": "call_complete",
        "name": "terminal",
        "arguments": '{"command":"true"}',
    }
    valid_output = {
        "type": "function_call_output",
        "call_id": "call_complete",
        "output": '{"exit_code":0}',
    }

    result = _preflight_codex_api_kwargs({
        "model": "gpt-5.6-sol",
        "instructions": "help",
        "input": [
            {
                "type": "function_call",
                "call_id": "call_interrupted",
                "name": "delegate_task",
                "arguments": '{"goal":"review"}',
            },
            {"role": "user", "content": "Hervat"},
            valid_call,
            valid_output,
        ],
        "store": False,
    })

    assert result["input"] == [
        {"role": "user", "content": "Hervat"},
        valid_call,
        valid_output,
    ]


def test_canonical_codex_output_preserves_wire_order_namespace_and_citations():
    ordered = [
        {
            "type": "reasoning",
            "encrypted_content": "enc",
            "summary": [],
            "_issuer_kind": "codex",
        },
        {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{
                "type": "output_text",
                "text": "Result",
                "annotations": [{
                    "type": "url_citation",
                    "url": "https://example.com/source",
                    "title": "Source",
                    "start_index": 0,
                    "end_index": 6,
                }],
            }],
        },
        {
            "type": "tool_search_call",
            "execution": "server",
            "call_id": None,
            "status": "completed",
            "arguments": {"paths": ["hermes_files"]},
        },
        {
            "type": "tool_search_output",
            "execution": "server",
            "call_id": None,
            "status": "completed",
            "tools": [{
                "type": "namespace",
                "name": "hermes_files",
                "description": "Files.",
                "tools": [{
                    "type": "function",
                    "name": "read_file",
                    "description": "Read.",
                    "parameters": {"type": "object", "properties": {}},
                    "strict": False,
                    "defer_loading": True,
                }],
            }],
        },
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"path":"README.md"}',
            "namespace": "hermes_files",
        },
    ]

    replayed = _chat_messages_to_responses_input([{
        "role": "assistant",
        "content": "Result\n\nSources:\n- [Source](https://example.com/source)",
        "codex_output_items": ordered,
        "tool_calls": [{
            "id": "call_1",
            "function": {"name": "read_file", "arguments": '{}'},
        }],
    }], current_issuer_kind="codex")

    assert [item["type"] for item in replayed] == [
        "reasoning", "message", "tool_search_call", "tool_search_output", "function_call",
    ]
    assert replayed[-1]["namespace"] == "hermes_files"
    assert replayed[1]["content"][0]["annotations"][0]["url"] == (
        "https://example.com/source"
    )


def test_normalize_preserves_citations_tool_search_and_provider_metrics():
    citation = SimpleNamespace(
        type="url_citation",
        url="https://example.com/source",
        title="Primary source",
        start_index=0,
        end_index=7,
    )
    response = SimpleNamespace(
        status="completed",
        prompt_cache_retention="24h",
        service_tier="auto",
        tool_usage=SimpleNamespace(web_search=SimpleNamespace(num_requests=2)),
        output=[
            SimpleNamespace(
                type="tool_search_call", execution="server", call_id=None,
                status="completed", arguments={"paths": ["hermes_web"]},
            ),
            SimpleNamespace(
                type="tool_search_output", execution="server", call_id=None,
                status="completed", tools=[{"type": "namespace", "name": "hermes_web", "description": "Web.", "tools": [{"type": "function", "name": "web_extract", "description": "Extract.", "parameters": {"type": "object", "properties": {}}, "strict": False, "defer_loading": True}]}],
            ),
            SimpleNamespace(
                type="web_search_call", status="completed",
                action=SimpleNamespace(sources=[
                    {"url": "https://example.com/source", "title": "Primary source", "type": "url"},
                    {"url": "https://example.com/secondary", "title": "Secondary", "type": "url"},
                ]),
            ),
            SimpleNamespace(
                type="message", role="assistant", status="completed",
                content=[SimpleNamespace(
                    type="output_text", text="Result", annotations=[citation],
                )],
            ),
            SimpleNamespace(
                type="function_call", status="completed", call_id="call_1",
                id="fc_1", name="web_extract", arguments='{"url":"https://example.com"}',
                namespace="hermes_web",
            ),
        ],
    )

    assistant_message, finish_reason = _normalize_codex_response(response)

    assert finish_reason == "tool_calls"
    assert assistant_message.content == (
        "Result\n\nSources:\n- [Primary source](https://example.com/source)"
    )
    assert assistant_message.codex_citations == [{
        "type": "url_citation",
        "url": "https://example.com/source",
        "title": "Primary source",
        "start_index": 0,
        "end_index": 7,
    }]
    assert [item["type"] for item in assistant_message.codex_tool_search_items] == [
        "tool_search_call", "tool_search_output",
    ]
    assert [item["type"] for item in assistant_message.codex_output_items] == [
        "tool_search_call", "tool_search_output", "message", "function_call",
    ]
    assert assistant_message.codex_output_items[-1]["namespace"] == "hermes_web"
    assert assistant_message.tool_calls[0].namespace == "hermes_web"
    assert assistant_message.codex_output_items[2]["content"][0]["annotations"] == [
        assistant_message.codex_citations[0]
    ]
    assert assistant_message.provider_metrics == {
        "prompt_cache_retention": "24h",
        "service_tier": "auto",
        "tool_usage": {"web_search": {"num_requests": 2}},
        "server_tool_calls": {"tool_search": 1, "web_search": 1},
        "web_search_sources": [
            {"url": "https://example.com/source", "title": "Primary source", "type": "url"},
            {"url": "https://example.com/secondary", "title": "Secondary", "type": "url"},
        ],
    }


def test_normalize_deduplicates_citation_urls_already_rendered():
    response = SimpleNamespace(
        status="completed",
        output=[SimpleNamespace(
            type="message", role="assistant", status="completed",
            content=[SimpleNamespace(
                type="output_text",
                text="See https://example.com/source",
                annotations=[SimpleNamespace(
                    type="url_citation", url="https://example.com/source",
                    title="Source", start_index=4, end_index=30,
                )],
            )],
        )],
    )

    assistant_message, _ = _normalize_codex_response(response)

    assert assistant_message.content == "See https://example.com/source"
    assert len(assistant_message.codex_citations) == 1


def test_citation_source_rendering_escapes_untrusted_markdown():
    response = SimpleNamespace(
        status="completed",
        output=[SimpleNamespace(
            type="message", role="assistant", status="completed",
            content=[SimpleNamespace(
                type="output_text",
                text="Result",
                annotations=[SimpleNamespace(
                    type="url_citation",
                    url="https://example.com/a_(b)",
                    title="Bad\n[title]",
                    start_index=0,
                    end_index=6,
                )],
            )],
        )],
    )

    assistant_message, _ = _normalize_codex_response(response)

    assert "Bad \\[title\\]" in assistant_message.content
    assert "https://example.com/a_%28b%29" in assistant_message.content


def test_preflight_still_rejects_unknown_tool_type():
    kwargs = {
        "model": "grok-composer-2.5-fast",
        "instructions": "You are helpful.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
        "store": False,
        "tools": [{"type": "totally_made_up_tool"}],
    }
    with pytest.raises(ValueError, match="unsupported type"):
        _preflight_codex_api_kwargs(kwargs, allow_stream=True)


# ---------------------------------------------------------------------------
# _format_responses_error — adapted from anomalyco/opencode#28757.
# Provider failures should surface BOTH the code (rate_limit_exceeded /
# context_length_exceeded / internal_error / server_error) and the message,
# so consumers can tell rate limits apart from context-length failures and
# both apart from generic stream drops.
# ---------------------------------------------------------------------------


def test_format_responses_error_combines_code_and_message():
    err = {"code": "rate_limit_exceeded", "message": "Slow down"}
    assert _format_responses_error(err, "failed") == "rate_limit_exceeded: Slow down"


def test_format_responses_error_message_only():
    err = {"message": "Upstream model unavailable"}
    assert _format_responses_error(err, "failed") == "Upstream model unavailable"


def test_format_responses_error_code_only_when_message_empty():
    # Some providers/proxies emit a code with an empty message body. We
    # used to fall back to ``str(error_obj)`` — a dict dump — which leaked
    # ``{'code': 'internal_error', 'message': ''}`` into chat output. Now
    # the bare code is surfaced, which is the meaningful field.
    err = {"code": "internal_error", "message": ""}
    assert _format_responses_error(err, "failed") == "internal_error"


def test_format_responses_error_code_only_when_message_missing():
    err = {"code": "server_error"}
    assert _format_responses_error(err, "failed") == "server_error"


def test_format_responses_error_attribute_style_payload():
    # SDK objects expose ``code``/``message`` as attributes rather than dict
    # keys. The helper must accept both shapes since the Responses SDK
    # returns SimpleNamespace-style objects on ``response.failed``.
    err = SimpleNamespace(code="context_length_exceeded", message="too long")
    assert _format_responses_error(err, "failed") == "context_length_exceeded: too long"


def test_format_responses_error_falls_back_to_status_when_empty():
    assert (
        _format_responses_error(None, "failed")
        == "Responses API returned status 'failed'"
    )
    assert (
        _format_responses_error(None, "cancelled")
        == "Responses API returned status 'cancelled'"
    )


def test_format_responses_error_stringifies_opaque_payload():
    # Last-resort: a provider sent something that isn't a dict and has no
    # code/message attributes. Surface its repr rather than swallow it
    # silently — at least it's visible in logs.
    assert _format_responses_error("opaque sentinel", "failed") == "opaque sentinel"


def test_format_responses_error_ignores_non_string_code_message():
    # Defensive: a malformed gateway could send numbers/objects in these
    # fields. We don't want to crash; we want a best-effort string.
    err = {"code": 500, "message": None}
    assert _format_responses_error(err, "failed") == "500"


def test_normalize_codex_response_failed_includes_code_in_error():
    """Regression: response_status == 'failed' should surface the error
    code, not just the message. Used to leak a bare 'Slow down' string
    that was indistinguishable from a generic stream truncation."""
    # ``output`` non-empty so we don't trip the "no output items" guard
    # before reaching the failed-status branch. Real failed responses
    # often DO carry a partial message item alongside the error.
    response = SimpleNamespace(
        status="failed",
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                status="incomplete",
                content=[SimpleNamespace(type="output_text", text="partial")],
            ),
        ],
        error={"code": "rate_limit_exceeded", "message": "Slow down"},
    )
    with pytest.raises(RuntimeError, match=r"^rate_limit_exceeded: Slow down$"):
        _normalize_codex_response(response)


def test_normalize_codex_response_failed_with_message_only():
    """Backwards-compat: a failed response with only a message field
    (no code) should still surface that message verbatim."""
    response = SimpleNamespace(
        status="failed",
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                status="incomplete",
                content=[SimpleNamespace(type="output_text", text="partial")],
            ),
        ],
        error={"message": "model error"},
    )
    with pytest.raises(RuntimeError, match=r"^model error$"):
        _normalize_codex_response(response)
