"""OpenAI Responses API (Codex) transport.

Delegates to the existing adapter functions in agent/codex_responses_adapter.py.
This transport owns format conversion and normalization — NOT client lifecycle,
streaming, or the _run_codex_stream() call path.
"""

import hashlib
import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from agent.transports.base import ProviderTransport
from agent.transports.types import NormalizedResponse, ToolCall


_CODEX_NATIVE_TOOL_SEARCH_MIN_FUNCTIONS = 8
_CODEX_NATIVE_TOOL_SEARCH_SCHEMA_BUDGET_CHARS = 12_000
_CODEX_NAMESPACE_MAX_FUNCTIONS = 8
_CODEX_DEFAULT_EAGER_TOOLS = (
    "terminal", "read_file", "search_files", "patch", "skill_view",
)
_CODEX_WEB_SEARCH_CONTEXT_SIZES = {"low", "medium", "high"}


def _codex_supports_native_tool_search(model: str) -> bool:
    """Return whether the Codex model supports hosted ``tool_search``."""
    match = re.search(r"(?:^|/)gpt-(\d+)\.(\d+)", str(model or "").lower())
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (5, 4)


def _codex_native_tool_search_enabled(params: Dict[str, Any]) -> bool:
    """Honor the config-derived per-request feature flag."""
    return params.get("native_tool_search", True) is not False


def _codex_tool_category(name: str) -> str:
    """Map Hermes function names to compact, model-searchable namespaces."""
    normalized = str(name or "").strip().lower()
    if normalized.startswith("mcp__"):
        parts = normalized.split("__")
        server = parts[1] if len(parts) > 2 and parts[1] else "tools"
        return f"mcp_{server}"
    if normalized.startswith("browser_"):
        return "browser"
    if normalized in {"terminal", "process"}:
        return "terminal"
    if normalized in {"read_file", "write_file", "search_files", "patch"}:
        return "files"
    if normalized.startswith("skill_") or normalized == "skills_list":
        return "skills"
    if normalized in {"memory", "fact_store", "fact_feedback", "session_search"}:
        return "memory"
    if normalized in {"image_generate", "vision_analyze", "text_to_speech"}:
        return "media"
    if normalized in {"cronjob", "delegate_task", "clarify", "todo"}:
        return "workflow"
    if normalized.startswith("web_"):
        return "web"
    return "general"


def _codex_native_tool_search_tools(
    tools: Optional[List[Dict[str, Any]]],
    *,
    min_functions: int = _CODEX_NATIVE_TOOL_SEARCH_MIN_FUNCTIONS,
    schema_budget_chars: int = _CODEX_NATIVE_TOOL_SEARCH_SCHEMA_BUDGET_CHARS,
    eager_tools: Optional[List[str]] = None,
) -> tuple[Optional[List[Dict[str, Any]]], Dict[str, Any]]:
    """Build a cache-stable eager/deferred tool plan from static schema cost.

    The decision never learns mid-conversation: it depends only on config and the
    byte-stable tool inventory, preserving prompt-cache prefixes. Small/cheap
    inventories remain eager; large inventories keep a fixed set of high-frequency
    core tools eager and defer the rest into hosted-search namespaces.
    """
    metrics: Dict[str, Any] = {
        "tool_search_enabled": False,
        "tool_schema_chars": 0,
        "eager_tool_count": 0,
        "deferred_tool_count": 0,
    }
    if not tools:
        return tools, metrics
    functions = [tool for tool in tools if tool.get("type") == "function"]
    metrics["tool_schema_chars"] = len(json.dumps(
        functions, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ))
    try:
        min_functions = max(1, int(min_functions))
    except (TypeError, ValueError):
        min_functions = _CODEX_NATIVE_TOOL_SEARCH_MIN_FUNCTIONS
    try:
        schema_budget_chars = max(1, int(schema_budget_chars))
    except (TypeError, ValueError):
        schema_budget_chars = _CODEX_NATIVE_TOOL_SEARCH_SCHEMA_BUDGET_CHARS
    if (
        len(functions) < min_functions
        and metrics["tool_schema_chars"] <= schema_budget_chars
    ):
        metrics["eager_tool_count"] = len(functions)
        return tools, metrics

    eager_names = {
        str(name).strip() for name in (eager_tools or _CODEX_DEFAULT_EAGER_TOOLS)
        if str(name).strip()
    }
    eager: List[Dict[str, Any]] = []
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for tool in functions:
        name = str(tool.get("name") or "")
        if name in eager_names:
            eager.append(tool)
            continue
        deferred = dict(tool)
        deferred["defer_loading"] = True
        grouped[_codex_tool_category(name)].append(deferred)

    if not grouped:
        metrics["eager_tool_count"] = len(functions)
        return tools, metrics

    namespaces: List[Dict[str, Any]] = []
    for category in sorted(grouped):
        category_tools = grouped[category]
        for index in range(0, len(category_tools), _CODEX_NAMESPACE_MAX_FUNCTIONS):
            chunk = category_tools[index:index + _CODEX_NAMESPACE_MAX_FUNCTIONS]
            suffix = "" if len(category_tools) <= _CODEX_NAMESPACE_MAX_FUNCTIONS else f"_{index // _CODEX_NAMESPACE_MAX_FUNCTIONS + 1}"
            namespaces.append({
                "type": "namespace",
                "name": f"hermes_{category}{suffix}",
                "description": f"Hermes {category.replace('_', ' ')} tools.",
                "tools": chunk,
            })

    builtins = [tool for tool in tools if tool.get("type") != "function"]
    metrics.update({
        "tool_search_enabled": True,
        "eager_tool_count": len(eager),
        "deferred_tool_count": sum(len(group) for group in grouped.values()),
    })
    return [*builtins, *eager, *namespaces, {"type": "tool_search"}], metrics


def _codex_web_search_tool(config: Any) -> tuple[Dict[str, Any], bool]:
    """Normalize optional first-party Codex web-search controls."""
    tool: Dict[str, Any] = {"type": "web_search"}
    include_sources = True
    if not isinstance(config, dict):
        return tool, include_sources
    context_size = str(config.get("search_context_size") or "").strip().lower()
    if context_size in _CODEX_WEB_SEARCH_CONTEXT_SIZES:
        tool["search_context_size"] = context_size
    domains = config.get("allowed_domains")
    if isinstance(domains, list):
        cleaned = [
            str(domain).strip().lower()
            for domain in domains
            if isinstance(domain, str) and str(domain).strip()
        ]
        if cleaned:
            tool["filters"] = {"allowed_domains": cleaned[:100]}
    location = config.get("user_location")
    if isinstance(location, dict):
        normalized_location = {"type": "approximate"}
        for key in ("country", "region", "city", "timezone"):
            value = location.get(key)
            if isinstance(value, str) and value.strip():
                normalized_location[key] = value.strip()
        if len(normalized_location) > 1:
            tool["user_location"] = normalized_location
    if config.get("include_sources") is False:
        include_sources = False
    return tool, include_sources


def _content_cache_key(instructions: str, tools: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """Content-address the prompt cache key from the static request prefix.

    Returns ``pck_<sha256[:24]>`` of (instructions + sorted tool schemas), or
    None when there is nothing static to key on. The cache key is a routing
    hint only — never a correctness boundary — so two requests sharing a system
    prompt and tool set intentionally resolve to the same warm prefix bucket.

    The fix this exists for: recurring cron jobs build session_id as
    ``cron_<id>_<timestamp>``, so using session_id as the cache key made every
    fire cache-cold. The static prefix (identity + tools) is identical across
    fires, so hashing it gives a stable key that stays warm within the
    provider's cache TTL. Sorting tools by name keeps the hash insertion-order
    independent.
    """
    if not instructions and not tools:
        return None
    tools_part = ""
    if tools:
        sorted_tools = sorted(
            (t for t in tools if isinstance(t, dict)),
            key=lambda t: str(t.get("name") or t.get("type") or ""),
        )
        tools_part = json.dumps(
            sorted_tools, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    # \x00 separator so instructions ending in the tool JSON can't collide with
    # a request whose instructions contain that JSON and whose tools are empty.
    content = f"{instructions or ''}\x00{tools_part}"
    digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"pck_{digest}"


class ResponsesApiTransport(ProviderTransport):
    """Transport for api_mode='codex_responses'.

    Wraps the functions extracted into codex_responses_adapter.py (PR 1).
    """

    # Issuer kind of the most recent build_kwargs / convert_messages call.
    # Used as a fallback when normalize_response is invoked without an
    # explicit ``issuer_kind`` kwarg, so reasoning items captured from a
    # response are stamped with the endpoint that minted them. Plain class
    # attribute default; mutated on the instance, not the class.
    _last_issuer_kind: Optional[str] = None
    _last_request_metrics: Optional[Dict[str, Any]] = None

    @property
    def api_mode(self) -> str:
        return "codex_responses"

    def _resolve_issuer_kind(self, params: Dict[str, Any]) -> str:
        """Classify the current Responses endpoint from transport params."""
        from agent.codex_responses_adapter import _classify_responses_issuer
        return _classify_responses_issuer(
            is_xai_responses=bool(params.get("is_xai_responses")),
            is_github_responses=bool(params.get("is_github_responses")),
            is_codex_backend=bool(params.get("is_codex_backend")),
            base_url=params.get("base_url"),
        )

    def convert_messages(self, messages: List[Dict[str, Any]], **kwargs) -> Any:
        """Convert OpenAI chat messages to Responses API input items."""
        from agent.codex_responses_adapter import _chat_messages_to_responses_input
        issuer = self._resolve_issuer_kind(kwargs)
        self._last_issuer_kind = issuer
        return _chat_messages_to_responses_input(
            messages,
            is_xai_responses=bool(kwargs.get("is_xai_responses")),
            replay_encrypted_reasoning=bool(
                kwargs.get("replay_encrypted_reasoning", True)
            ),
            current_issuer_kind=issuer,
        )

    def convert_tools(self, tools: List[Dict[str, Any]]) -> Any:
        """Convert OpenAI tool schemas to Responses API function definitions."""
        from agent.codex_responses_adapter import _responses_tools
        return _responses_tools(tools)

    def build_kwargs(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **params,
    ) -> Dict[str, Any]:
        """Build Responses API kwargs.

        Calls convert_messages and convert_tools internally.

        params:
            instructions: str — system prompt (extracted from messages[0] if not given)
            reasoning_config: dict | None — {effort, enabled}
            session_id: str | None — transcript/session id; drives the xAI
                x-grok-conv-id header and the Codex cache-scope headers, and is
                the fallback prompt_cache_key when there is no static prefix to
                content-address
            max_tokens: int | None — max_output_tokens
            timeout: float | None — per-request timeout forwarded to the SDK
            request_overrides: dict | None — extra kwargs merged in
            provider: str | None — provider name for backend-specific logic
            base_url: str | None — endpoint URL
            base_url_hostname: str | None — hostname for backend detection
            is_github_responses: bool — Copilot/GitHub models backend
            is_codex_backend: bool — chatgpt.com/backend-api/codex
            is_xai_responses: bool — xAI/Grok backend
            github_reasoning_extra: dict | None — Copilot reasoning params
        """
        from agent.codex_responses_adapter import (
            _chat_messages_to_responses_input,
            _responses_tools,
        )

        from run_agent import DEFAULT_AGENT_IDENTITY

        instructions = params.get("instructions", "")
        payload_messages = messages
        if not instructions:
            if messages and messages[0].get("role") == "system":
                instructions = str(messages[0].get("content") or "").strip()
                payload_messages = messages[1:]
        if not instructions:
            instructions = DEFAULT_AGENT_IDENTITY

        is_github_responses = params.get("is_github_responses", False)
        is_codex_backend = params.get("is_codex_backend", False)
        is_xai_responses = params.get("is_xai_responses", False)
        replay_encrypted_reasoning = bool(
            params.get("replay_encrypted_reasoning", True)
        )

        # Resolve the issuing endpoint for this call. Stashed on the
        # transport so normalize_response can stamp it onto reasoning
        # items captured from the response, and passed to the input
        # converter so foreign-issuer reasoning blocks in history are
        # dropped before the API rejects them.
        issuer_kind = self._resolve_issuer_kind(params)
        self._last_issuer_kind = issuer_kind

        # Resolve reasoning effort
        reasoning_effort = "medium"
        reasoning_enabled = True
        reasoning_config = params.get("reasoning_config")
        if reasoning_config and isinstance(reasoning_config, dict):
            if reasoning_config.get("enabled") is False:
                reasoning_enabled = False
            elif reasoning_config.get("effort"):
                reasoning_effort = reasoning_config["effort"]

        _effort_clamp = {"minimal": "low"}
        reasoning_effort = _effort_clamp.get(reasoning_effort, reasoning_effort)

        response_tools = _responses_tools(tools)

        # Provider-native server-side web search.
        #
        # xAI's and ChatGPT/Codex's Responses endpoints have a *native*,
        # server-executed web search. When the agent has the client-side
        # ``web_search`` function (the web toolset is enabled), replace that
        # declaration with the provider built-in. Two tools sharing the name
        # ``web_search`` are rejected, so the client function must be dropped.
        # Other client-side tools remain available through Hermes's agent loop.
        #
        # For ChatGPT/Codex this is the first-party search surfaced by Codex
        # CLI's ``--search`` flag. It uses Hermes's existing Codex OAuth and
        # needs no separate Brave/Tavily/Firecrawl credential.
        #
        # The swap is a 1:1 replacement, not an additive grant: sessions that
        # do not expose ``web_search`` do not gain it. Native results arrive in
        # the model response instead of Hermes's tool-result/citation plumbing.
        # Generic OpenAI-compatible and GitHub Responses endpoints keep the
        # client-side function.
        include_web_search_sources = False
        if (is_xai_responses or is_codex_backend) and response_tools:
            has_client_web_search = any(
                isinstance(t, dict) and t.get("name") == "web_search"
                for t in response_tools
            )
            if has_client_web_search:
                filtered = [
                    t for t in response_tools
                    if not (isinstance(t, dict) and t.get("name") == "web_search")
                ]
                if is_codex_backend:
                    native_web_tool, include_web_search_sources = _codex_web_search_tool(
                        params.get("native_web_search")
                    )
                    filtered.append(native_web_tool)
                else:
                    filtered.append({"type": "web_search"})
                response_tools = filtered

        # OpenAI's Codex Responses backend can search deferred tool schemas
        # server-side on gpt-5.4+. This keeps large Hermes/MCP parameter schemas
        # out of the model context until needed while preserving the full trusted
        # inventory in the request. Smaller toolsets stay eager to avoid an
        # unnecessary hosted-search step.
        request_metrics: Dict[str, Any] = {}
        if (
            is_codex_backend
            and _codex_supports_native_tool_search(model)
            and _codex_native_tool_search_enabled(params)
        ):
            response_tools, request_metrics = _codex_native_tool_search_tools(
                response_tools,
                min_functions=params.get(
                    "native_tool_search_min_functions",
                    _CODEX_NATIVE_TOOL_SEARCH_MIN_FUNCTIONS,
                ),
                schema_budget_chars=params.get(
                    "native_tool_search_schema_budget_chars",
                    _CODEX_NATIVE_TOOL_SEARCH_SCHEMA_BUDGET_CHARS,
                ),
                eager_tools=params.get("native_tool_search_eager_tools"),
            )
        self._last_request_metrics = request_metrics or None

        # ``tools`` MUST be omitted entirely when there are no functions to
        # expose: the openai SDK's ``responses.stream()`` / ``responses.parse()``
        # eagerly call ``_make_tools(tools)`` which does ``for tool in tools``
        # without a None guard, so passing ``tools=None`` raises
        # ``TypeError: 'NoneType' object is not iterable`` before any HTTP
        # request is issued (openai==2.24.0).  Reported for the
        # ``openai-codex`` / ``gpt-5.5`` combo on chatgpt.com/backend-api/codex
        # (#32892) when the agent runs without external tools registered.
        kwargs = {
            "model": model,
            "instructions": instructions,
            "input": _chat_messages_to_responses_input(
                payload_messages,
                is_xai_responses=is_xai_responses,
                replay_encrypted_reasoning=replay_encrypted_reasoning,
                current_issuer_kind=issuer_kind,
            ),
            "store": False,
        }
        if response_tools:
            kwargs["tools"] = response_tools
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = True

        session_id = params.get("session_id")
        # prompt_cache_key is content-addressed from the static prefix
        # (instructions + tools), NOT session_id — recurring cron jobs carry a
        # per-fire timestamp in session_id (cron_<id>_<ts>) that made every run
        # cache-cold. session_id is left untouched for transcript isolation and
        # the cache-scope routing headers below. Falls back to session_id when
        # there is no static content to hash.
        cache_key = _content_cache_key(instructions, response_tools) or session_id
        # xAI Responses takes prompt_cache_key in extra_body (set further
        # down); GitHub Models opts out of cache-key routing entirely.
        if not is_github_responses and not is_xai_responses and cache_key:
            kwargs["prompt_cache_key"] = cache_key

        if reasoning_enabled and is_xai_responses:
            from agent.model_metadata import grok_supports_reasoning_effort

            # Ask xAI to echo back encrypted reasoning items so we can
            # replay them on subsequent turns for cross-turn coherence.
            # See agent/codex_responses_adapter._chat_messages_to_responses_input
            # for the May 2026 reversal of the earlier suppression gate.
            kwargs["include"] = (
                ["reasoning.encrypted_content"] if replay_encrypted_reasoning else []
            )
            # xAI rejects `reasoning.effort` on grok-4 / grok-4-fast / grok-3
            # / grok-code-fast / grok-4.20-0309-* with HTTP 400 even though
            # those models reason natively. Only send the effort dial when
            # the target model is on the allowlist; otherwise send no
            # `reasoning` key at all and let the model reason on its own.
            if grok_supports_reasoning_effort(model):
                kwargs["reasoning"] = {"effort": reasoning_effort}
        elif reasoning_enabled:
            if is_github_responses:
                github_reasoning = params.get("github_reasoning_extra")
                if github_reasoning is not None:
                    kwargs["reasoning"] = github_reasoning
            else:
                kwargs["reasoning"] = {"effort": reasoning_effort, "summary": "auto"}
                kwargs["include"] = (
                    ["reasoning.encrypted_content"] if replay_encrypted_reasoning else []
                )
        elif not is_github_responses and not is_xai_responses:
            kwargs["include"] = []

        if include_web_search_sources:
            include = list(kwargs.get("include") or [])
            source_path = "web_search_call.action.sources"
            if source_path not in include:
                include.append(source_path)
            kwargs["include"] = include

        request_overrides = params.get("request_overrides")
        if request_overrides:
            kwargs.update(request_overrides)

        # xAI Responses API rejects ``service_tier`` (HTTP 400 "Argument not
        # supported: service_tier") — hit when ``/fast`` priority-processing
        # mode lingers from a prior model in the same session, or when a
        # user explicitly sets ``agent.service_tier`` in config.yaml.  The
        # main-loop guard (``resolve_fast_mode_overrides`` only returns
        # ``service_tier`` for OpenAI fast-eligible models) doesn't cover
        # those leak paths, so strip defensively when targeting xAI.  See
        # #28490 for the original report.
        if is_xai_responses:
            kwargs.pop("service_tier", None)

        # Forward per-request timeout to the SDK so OpenAI/Anthropic clients
        # honor it.  Without this, ``providers.<id>.request_timeout_seconds``
        # is silently dropped on the main agent Codex path while the
        # chat_completions path and auxiliary Codex adapter both forward it.
        timeout = kwargs.get("timeout", params.get("timeout"))
        if (
            isinstance(timeout, (int, float))
            and not isinstance(timeout, bool)
            and 0 < float(timeout) < float("inf")
        ):
            kwargs["timeout"] = float(timeout)
        else:
            kwargs.pop("timeout", None)

        if is_codex_backend:
            # The Codex backend rejects body-level ``extra_headers`` with
            # HTTP 400, but the OpenAI SDK's ``extra_headers`` kwarg maps
            # to actual HTTP request headers (not body fields).  We need
            # these headers for cache-scope routing so prompt cache hits
            # remain high.  Send session_id / x-client-request-id as HTTP
            # headers while keeping ``prompt_cache_key`` in the body for
            # standard OpenAI routing as a belt-and-braces fallback.
            cache_scope_id = str(session_id or "").strip()
            if cache_scope_id:
                existing_extra_headers = kwargs.get("extra_headers")
                merged_extra_headers: Dict[str, str] = {}
                if isinstance(existing_extra_headers, dict):
                    merged_extra_headers.update(
                        {
                            str(key): str(value)
                            for key, value in existing_extra_headers.items()
                            if key and value is not None
                        }
                    )
                merged_extra_headers["session_id"] = cache_scope_id
                merged_extra_headers["x-client-request-id"] = cache_scope_id
                kwargs["extra_headers"] = merged_extra_headers

        max_tokens = params.get("max_tokens")
        if max_tokens is not None and not is_codex_backend:
            kwargs["max_output_tokens"] = max_tokens

        if is_xai_responses and session_id:
            existing_extra_headers = kwargs.get("extra_headers")
            merged_extra_headers: Dict[str, str] = {}
            if isinstance(existing_extra_headers, dict):
                merged_extra_headers.update(
                    {
                        str(key): str(value)
                        for key, value in existing_extra_headers.items()
                        if key and value is not None
                    }
                )
            merged_extra_headers["x-grok-conv-id"] = session_id
            kwargs["extra_headers"] = merged_extra_headers

            # xAI Responses cache-routing — body-level field per
            # https://docs.x.ai/developers/advanced-api-usage/prompt-caching/maximizing-cache-hits.
            # Sent via extra_body (not the typed kwarg) so it survives openai
            # SDK builds whose Responses.stream() signature has dropped the field.
            existing_extra_body = kwargs.get("extra_body")
            merged_extra_body: Dict[str, Any] = {}
            if isinstance(existing_extra_body, dict):
                merged_extra_body.update(existing_extra_body)
            merged_extra_body.setdefault("prompt_cache_key", cache_key)
            kwargs["extra_body"] = merged_extra_body

        return kwargs

    def normalize_response(self, response: Any, **kwargs) -> NormalizedResponse:
        """Normalize Codex Responses API response to NormalizedResponse."""
        from agent.codex_responses_adapter import (
            _normalize_codex_response,
        )

        # Issuer for this response = explicit kwarg if the caller knows it,
        # otherwise the stash from the matching build_kwargs/convert_messages
        # call. Either way it gets stamped onto reasoning items so future
        # turns can detect a model swap and drop foreign-issuer blobs.
        issuer_kind = kwargs.get("issuer_kind") or self._last_issuer_kind
        # _normalize_codex_response returns (SimpleNamespace, finish_reason_str)
        msg, finish_reason = _normalize_codex_response(response, issuer_kind=issuer_kind)

        tool_calls = None
        if msg and msg.tool_calls:
            tool_calls = []
            for tc in msg.tool_calls:
                provider_data = {}
                if hasattr(tc, "call_id") and tc.call_id:
                    provider_data["call_id"] = tc.call_id
                if hasattr(tc, "response_item_id") and tc.response_item_id:
                    provider_data["response_item_id"] = tc.response_item_id
                if hasattr(tc, "namespace") and tc.namespace:
                    provider_data["namespace"] = tc.namespace
                tool_calls.append(ToolCall(
                    id=tc.id if hasattr(tc, "id") else (tc.function.name if hasattr(tc, "function") else None),
                    name=tc.function.name if hasattr(tc, "function") else getattr(tc, "name", ""),
                    arguments=tc.function.arguments if hasattr(tc, "function") else getattr(tc, "arguments", "{}"),
                    provider_data=provider_data or None,
                ))

        # Extract reasoning items for provider_data
        provider_data = {}
        if msg and hasattr(msg, "codex_reasoning_items") and msg.codex_reasoning_items:
            provider_data["codex_reasoning_items"] = msg.codex_reasoning_items
        if msg and hasattr(msg, "codex_message_items") and msg.codex_message_items:
            provider_data["codex_message_items"] = msg.codex_message_items
        if msg and hasattr(msg, "codex_tool_search_items") and msg.codex_tool_search_items:
            provider_data["codex_tool_search_items"] = msg.codex_tool_search_items
        if msg and hasattr(msg, "codex_output_items") and msg.codex_output_items:
            provider_data["codex_output_items"] = msg.codex_output_items
        if msg and hasattr(msg, "codex_citations") and msg.codex_citations:
            provider_data["codex_citations"] = msg.codex_citations
        response_metrics = dict(msg.provider_metrics) if (
            msg and hasattr(msg, "provider_metrics") and msg.provider_metrics
        ) else {}
        if self._last_request_metrics:
            response_metrics["request"] = dict(self._last_request_metrics)
        if response_metrics:
            provider_data["provider_metrics"] = response_metrics
        if msg and hasattr(msg, "reasoning_details") and msg.reasoning_details:
            provider_data["reasoning_details"] = msg.reasoning_details

        return NormalizedResponse(
            content=msg.content if msg else None,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            reasoning=msg.reasoning if msg and hasattr(msg, "reasoning") else None,
            usage=None,  # Codex usage is extracted separately in normalize_usage()
            provider_data=provider_data or None,
        )

    def validate_response(self, response: Any) -> bool:
        """Check Codex Responses API response has valid output structure.

        Returns True only if response.output is a non-empty list.
        Does NOT check output_text fallback — the caller handles that
        with diagnostic logging for stream backfill recovery.
        """
        if response is None:
            return False
        output = getattr(response, "output", None)
        if not isinstance(output, list) or not output:
            return False
        return True

    def preflight_kwargs(self, api_kwargs: Any, *, allow_stream: bool = False) -> dict:
        """Validate and sanitize Codex API kwargs before the call.

        Normalizes input items, strips unsupported fields, validates structure.
        """
        from agent.codex_responses_adapter import _preflight_codex_api_kwargs
        return _preflight_codex_api_kwargs(api_kwargs, allow_stream=allow_stream)

    def map_finish_reason(self, raw_reason: str) -> str:
        """Map Codex response.status to OpenAI finish_reason.

        Codex uses response.status ('completed', 'incomplete') +
        response.incomplete_details.reason for granular mapping.
        This method handles the simple status string; the caller
        should check incomplete_details separately for 'max_output_tokens'.
        """
        _MAP = {
            "completed": "stop",
            "incomplete": "length",
            "failed": "stop",
            "cancelled": "stop",
        }
        return _MAP.get(raw_reason, "stop")


# Auto-register on import
from agent.transports import register_transport  # noqa: E402

register_transport("codex_responses", ResponsesApiTransport)
