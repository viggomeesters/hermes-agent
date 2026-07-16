"""Safe provider-efficiency summaries shared by CLI and gateway /usage."""
from __future__ import annotations

from typing import Any


def provider_efficiency_lines(agent: Any, *, markdown: bool = False) -> list[str]:
    metrics = getattr(agent, "session_provider_metrics", None)
    cache_read = int(getattr(agent, "session_cache_read_tokens", 0) or 0)
    input_tokens = int(getattr(agent, "session_input_tokens", 0) or 0)
    if not isinstance(metrics, dict) and not cache_read:
        return []
    metrics = metrics if isinstance(metrics, dict) else {}
    lines = ["**Provider efficiency**" if markdown else "Provider efficiency"]
    if input_tokens > 0:
        lines.append(f"Cache hit: {cache_read:,}/{input_tokens:,} input tokens ({cache_read / input_tokens * 100:.1f}%)")
    elif cache_read:
        lines.append(f"Cached input: {cache_read:,} tokens")

    request = metrics.get("last_request")
    if isinstance(request, dict) and request:
        enabled = bool(request.get("tool_search_enabled"))
        eager = int(request.get("eager_tool_count") or 0)
        deferred = int(request.get("deferred_tool_count") or 0)
        schema_chars = int(request.get("tool_schema_chars") or 0)
        lines.append(
            f"Tool schemas: {schema_chars:,} chars · {eager} eager · {deferred} deferred"
            + (" · native search" if enabled else "")
        )

    calls = metrics.get("server_tool_calls")
    if isinstance(calls, dict) and calls:
        rendered = ", ".join(
            f"{name} {int(count)}" for name, count in sorted(calls.items())
            if isinstance(count, (int, float)) and count
        )
        if rendered:
            lines.append(f"Server tools: {rendered}")

    sources = metrics.get("web_search_sources")
    if isinstance(sources, list) and sources:
        lines.append(f"Web provenance: {len(sources)} unique source records")
    native_compactions = int(metrics.get("native_compactions") or 0)
    if native_compactions:
        lines.append(f"Native compactions: {native_compactions}")
    return lines if len(lines) > 1 else []
