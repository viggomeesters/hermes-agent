from agent.approval_surface import (
    ActionKind,
    AgentMode,
    ApprovalDecision,
    ApprovalSurface,
    classify_approval_surface,
    most_restrictive,
)


def test_plan_mode_blocks_writes():
    result = classify_approval_surface(AgentMode.PLAN, ActionKind.WRITE, has_visible_diff=True)

    assert result.decision is ApprovalDecision.BLOCK
    assert result.explicit_user_approval_required is True


def test_go_mode_workspace_write_with_visible_diff_is_show_not_ask():
    result = classify_approval_surface(AgentMode.GO, ActionKind.WRITE, has_visible_diff=True)

    assert result.decision is ApprovalDecision.SHOW
    assert result.visible_diff_required is True
    assert result.explicit_user_approval_required is False


def test_go_mode_write_without_diff_requires_approval():
    result = classify_approval_surface(AgentMode.GO, ActionKind.WRITE, has_visible_diff=False)

    assert result.decision is ApprovalDecision.ASK
    assert result.visible_diff_required is True


def test_public_payment_and_destructive_actions_require_ship_mode():
    assert classify_approval_surface(AgentMode.GO, ActionKind.PUBLIC).decision is ApprovalDecision.BLOCK
    assert classify_approval_surface(AgentMode.GO, ActionKind.PAYMENT).decision is ApprovalDecision.BLOCK
    assert classify_approval_surface(AgentMode.GO, ActionKind.DESTRUCTIVE).decision is ApprovalDecision.BLOCK
    assert classify_approval_surface(AgentMode.SHIP, ActionKind.PUBLIC).decision is ApprovalDecision.ASK
    assert classify_approval_surface(AgentMode.SHIP, ActionKind.DESTRUCTIVE).decision is ApprovalDecision.ASK


def test_mcp_write_and_network_require_approval():
    assert classify_approval_surface(AgentMode.GO, ActionKind.MCP_WRITE).decision is ApprovalDecision.ASK
    assert classify_approval_surface(AgentMode.GO, ActionKind.NETWORK).decision is ApprovalDecision.ASK


def test_most_restrictive_picks_highest_risk():
    result = most_restrictive(
        [
            ApprovalSurface(ApprovalDecision.SHOW, "show"),
            ApprovalSurface(ApprovalDecision.ASK, "ask"),
            ApprovalSurface(ApprovalDecision.ALLOW, "allow"),
        ]
    )

    assert result.decision is ApprovalDecision.ASK
