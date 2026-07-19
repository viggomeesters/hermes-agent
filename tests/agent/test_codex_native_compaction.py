from types import SimpleNamespace

from agent.conversation_compression import (
    _compact_context_via_codex_responses,
    _is_native_codex_responses_compaction,
)
from agent.codex_responses_adapter import _chat_messages_to_responses_input


class _Responses:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.kwargs = None

    def compact(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def _agent(response=None, error=None):
    responses = _Responses(response, error)
    compressor = SimpleNamespace(
        compression_count=0,
        last_prompt_tokens=100,
        awaiting_real_usage_after_compression=False,
        _last_compress_aborted=True,
        _last_summary_error="old",
        _last_compression_savings_pct=0.0,
        _ineffective_compression_count=0,
    )
    agent = SimpleNamespace(
        model="gpt-5.6-sol", session_id="session-1",
        client=SimpleNamespace(responses=responses),
        context_compressor=compressor,
        session_provider_metrics={"native_compactions": 0},
    )
    return agent, responses


def test_native_codex_compaction_builds_replayable_messages():
    response = SimpleNamespace(
        output=[
            SimpleNamespace(type="message", role="user", content=[
                SimpleNamespace(type="input_text", text="latest user turn")
            ]),
            SimpleNamespace(type="compaction_summary", encrypted_content="opaque"),
        ],
        usage=SimpleNamespace(input_tokens=123, output_tokens=45),
    )
    agent, responses = _agent(response=response)
    compacted = _compact_context_via_codex_responses(
        agent,
        [{"role": "user", "content": "old"}, {"role": "assistant", "content": "answer"}, {"role": "user", "content": "latest user turn"}],
        "system",
        approx_tokens=1000,
    )
    assert compacted[0]["role"] == "user"
    assert compacted[0]["content"] == "latest user turn"
    assert _chat_messages_to_responses_input(compacted, current_issuer_kind="codex") == [
        {"role": "user", "content": "latest user turn"},
        {"type": "compaction_summary", "encrypted_content": "opaque"},
    ]
    assert responses.kwargs["instructions"] == "system"
    assert agent.context_compressor.compression_count == 1
    assert agent.session_provider_metrics["native_compactions"] == 1


def test_native_codex_compaction_drops_interrupted_tool_call_before_resume():
    response = SimpleNamespace(
        output=[
            SimpleNamespace(type="message", role="user", content=[
                SimpleNamespace(type="input_text", text="Hervat")
            ]),
            SimpleNamespace(type="compaction_summary", encrypted_content="opaque"),
        ],
        usage=SimpleNamespace(input_tokens=123, output_tokens=45),
    )
    agent, responses = _agent(response=response)

    compacted = _compact_context_via_codex_responses(
        agent,
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call_interrupted",
                    "call_id": "call_interrupted",
                    "type": "function",
                    "function": {"name": "delegate_task", "arguments": '{"goal":"review"}'},
                }],
            },
            {"role": "user", "content": "Hervat"},
        ],
        "system",
        approx_tokens=1000,
    )

    assert compacted is not None
    assert responses.kwargs["input"] == [{"role": "user", "content": "Hervat"}]


def test_native_compaction_respects_external_context_engine():
    agent = SimpleNamespace(
        codex_responses_compaction="native",
        api_mode="codex_responses",
        provider="openai-codex",
        base_url="https://chatgpt.com/backend-api/codex",
        context_engine_name="lcm",
    )
    assert _is_native_codex_responses_compaction(agent) is False
    agent.context_engine_name = "compressor"
    assert _is_native_codex_responses_compaction(agent) is True


def test_native_codex_compaction_failure_returns_none_for_fallback():
    agent, _ = _agent(error=RuntimeError("unsupported"))
    assert _compact_context_via_codex_responses(
        agent, [{"role": "user", "content": "hello"}], "system", approx_tokens=100
    ) is None
    assert "unsupported" in agent._last_native_codex_compaction_error
