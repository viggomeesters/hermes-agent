from types import SimpleNamespace

from agent.provider_efficiency import provider_efficiency_lines


def test_provider_efficiency_lines_surface_safe_metrics():
    agent = SimpleNamespace(
        session_cache_read_tokens=400,
        session_input_tokens=1000,
        session_provider_metrics={
            "last_request": {
                "tool_search_enabled": True,
                "tool_schema_chars": 24000,
                "eager_tool_count": 5,
                "deferred_tool_count": 20,
            },
            "server_tool_calls": {"tool_search": 2, "web_search": 1},
            "web_search_sources": [{"url": "https://example.com"}],
            "native_compactions": 1,
        },
    )
    text = "\n".join(provider_efficiency_lines(agent))
    assert "40.0%" in text
    assert "5 eager · 20 deferred" in text
    assert "tool_search 2" in text
    assert "1 unique source" in text
    assert "Native compactions: 1" in text
