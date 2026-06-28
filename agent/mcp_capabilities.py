"""MCP capability taxonomy helpers.

Mined from FastMCP/MCP conventions: tools, resources and prompts are different
capabilities and should not share one trust policy. Tool annotations are useful
signals but never authoritative security decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Any


class McpCapabilityKind(str, Enum):
    TOOL = "tool"
    RESOURCE = "resource"
    RESOURCE_TEMPLATE = "resource_template"
    PROMPT = "prompt"


class McpRiskTier(str, Enum):
    CONTEXT = "context"
    READ_ONLY_TOOL = "read_only_tool"
    SIDE_EFFECT_TOOL = "side_effect_tool"
    DESTRUCTIVE_TOOL = "destructive_tool"
    PROMPT_TEMPLATE = "prompt_template"


@dataclass(frozen=True)
class McpCapabilityPolicy:
    kind: McpCapabilityKind
    risk_tier: McpRiskTier
    default_surface: str
    approval_required: bool
    trust_note: str


def classify_mcp_capability(
    kind: McpCapabilityKind | str,
    *,
    annotations: Mapping[str, Any] | None = None,
) -> McpCapabilityPolicy:
    """Classify an MCP capability for Hermes surfacing.

    `annotations` may include MCP-style hints such as `readOnlyHint`,
    `destructiveHint`, `idempotentHint` or `openWorldHint`. They are treated as
    advisory metadata only.
    """
    kind = McpCapabilityKind(kind)
    annotations = annotations or {}

    if kind is McpCapabilityKind.RESOURCE:
        return McpCapabilityPolicy(kind, McpRiskTier.CONTEXT, "context_provider", False, "resource content is context, not an executable tool")
    if kind is McpCapabilityKind.RESOURCE_TEMPLATE:
        return McpCapabilityPolicy(kind, McpRiskTier.CONTEXT, "query_context_provider", False, "resource template needs bounded query and provenance")
    if kind is McpCapabilityKind.PROMPT:
        return McpCapabilityPolicy(kind, McpRiskTier.PROMPT_TEMPLATE, "slash_command_candidate", True, "prompt templates require explicit allowlist before invocation")

    destructive = bool(annotations.get("destructiveHint"))
    read_only = bool(annotations.get("readOnlyHint"))
    open_world = bool(annotations.get("openWorldHint"))

    if destructive:
        return McpCapabilityPolicy(kind, McpRiskTier.DESTRUCTIVE_TOOL, "agent_tool_blocked_by_default", True, "destructive MCP tool hint requires explicit approval and must be treated as untrusted")
    if read_only and not open_world:
        return McpCapabilityPolicy(kind, McpRiskTier.READ_ONLY_TOOL, "agent_tool", False, "read-only hint can lower friction but remains advisory")
    return McpCapabilityPolicy(kind, McpRiskTier.SIDE_EFFECT_TOOL, "agent_tool_ask", True, "missing/read-write/open-world hints require approval")
