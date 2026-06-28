"""Approval surface primitives for presenting agent actions.

This module translates mined Cline/Codex approval lessons into a small,
deterministic classifier for Hermes UI/CLI surfaces. It does not enforce
permissions by itself; enforcement stays in existing approval/sandbox/tool code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class ApprovalDecision(str, Enum):
    ALLOW = "allow"
    SHOW = "show"
    ASK = "ask"
    BLOCK = "block"


class ActionKind(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    MCP_READ = "mcp_read"
    MCP_WRITE = "mcp_write"
    PUBLIC = "public"
    PAYMENT = "payment"
    DESTRUCTIVE = "destructive"


class AgentMode(str, Enum):
    REFLECT = "reflect"
    PLAN = "plan"
    GO = "go"
    SHIP = "ship"


@dataclass(frozen=True)
class ApprovalSurface:
    decision: ApprovalDecision
    reason: str
    visible_diff_required: bool = False
    explicit_user_approval_required: bool = False


_DECISION_RANK = {
    ApprovalDecision.ALLOW: 0,
    ApprovalDecision.SHOW: 1,
    ApprovalDecision.ASK: 2,
    ApprovalDecision.BLOCK: 3,
}


def most_restrictive(surfaces: Iterable[ApprovalSurface]) -> ApprovalSurface:
    items = list(surfaces)
    if not items:
        return ApprovalSurface(ApprovalDecision.ALLOW, "no risk signals")
    return max(items, key=lambda item: _DECISION_RANK[item.decision])


def classify_approval_surface(
    mode: AgentMode | str,
    action: ActionKind | str,
    *,
    outside_workspace: bool = False,
    has_visible_diff: bool = False,
    advertised_destructive: bool = False,
) -> ApprovalSurface:
    """Classify how an action should be surfaced before execution.

    The classifier is intentionally conservative:
    - reflect/plan are read-only modes;
    - writes need a visible diff when possible;
    - network/MCP writes/public/payment/destructive actions require explicit approval;
    - destructive/public/payment actions are blocked outside ship mode.
    """
    mode = AgentMode(mode)
    action = ActionKind(action)

    if action is ActionKind.READ or action is ActionKind.MCP_READ:
        return ApprovalSurface(ApprovalDecision.ALLOW, "read-only action")

    if mode in {AgentMode.REFLECT, AgentMode.PLAN}:
        return ApprovalSurface(
            ApprovalDecision.BLOCK,
            f"{mode.value} mode is read-only",
            explicit_user_approval_required=True,
        )

    if advertised_destructive or action is ActionKind.DESTRUCTIVE:
        return ApprovalSurface(
            ApprovalDecision.ASK if mode is AgentMode.SHIP else ApprovalDecision.BLOCK,
            "destructive action requires ship-mode approval",
            visible_diff_required=True,
            explicit_user_approval_required=True,
        )

    if action in {ActionKind.PUBLIC, ActionKind.PAYMENT}:
        return ApprovalSurface(
            ApprovalDecision.ASK if mode is AgentMode.SHIP else ApprovalDecision.BLOCK,
            "public/payment action requires explicit ship approval",
            visible_diff_required=True,
            explicit_user_approval_required=True,
        )

    if action in {ActionKind.NETWORK, ActionKind.MCP_WRITE}:
        return ApprovalSurface(
            ApprovalDecision.ASK,
            "network or side-effecting MCP action requires approval",
            explicit_user_approval_required=True,
        )

    if outside_workspace:
        return ApprovalSurface(
            ApprovalDecision.ASK,
            "action crosses workspace boundary",
            visible_diff_required=action is ActionKind.WRITE,
            explicit_user_approval_required=True,
        )

    if action is ActionKind.WRITE:
        if has_visible_diff:
            return ApprovalSurface(
                ApprovalDecision.SHOW,
                "workspace write with visible diff",
                visible_diff_required=True,
            )
        return ApprovalSurface(
            ApprovalDecision.ASK,
            "workspace write has no visible diff",
            visible_diff_required=True,
            explicit_user_approval_required=True,
        )

    if action is ActionKind.EXECUTE:
        return ApprovalSurface(ApprovalDecision.SHOW, "workspace command should be shown before execution")

    return ApprovalSurface(ApprovalDecision.ASK, "unknown action requires approval", explicit_user_approval_required=True)
