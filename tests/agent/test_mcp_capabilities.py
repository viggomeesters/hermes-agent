from agent.mcp_capabilities import (
    McpCapabilityKind,
    McpRiskTier,
    classify_mcp_capability,
)


def test_resources_are_context_not_tools():
    policy = classify_mcp_capability(McpCapabilityKind.RESOURCE)

    assert policy.risk_tier is McpRiskTier.CONTEXT
    assert policy.default_surface == "context_provider"
    assert policy.approval_required is False


def test_prompts_require_allowlist_before_command_surface():
    policy = classify_mcp_capability(McpCapabilityKind.PROMPT)

    assert policy.risk_tier is McpRiskTier.PROMPT_TEMPLATE
    assert policy.approval_required is True


def test_read_only_tool_can_be_low_friction_when_not_open_world():
    policy = classify_mcp_capability(
        McpCapabilityKind.TOOL,
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )

    assert policy.risk_tier is McpRiskTier.READ_ONLY_TOOL
    assert policy.approval_required is False


def test_open_world_read_only_tool_still_requires_approval():
    policy = classify_mcp_capability(
        McpCapabilityKind.TOOL,
        annotations={"readOnlyHint": True, "openWorldHint": True},
    )

    assert policy.risk_tier is McpRiskTier.SIDE_EFFECT_TOOL
    assert policy.approval_required is True


def test_destructive_tool_hint_is_blocked_by_default_surface():
    policy = classify_mcp_capability(McpCapabilityKind.TOOL, annotations={"destructiveHint": True})

    assert policy.risk_tier is McpRiskTier.DESTRUCTIVE_TOOL
    assert policy.default_surface == "agent_tool_blocked_by_default"
    assert policy.approval_required is True
