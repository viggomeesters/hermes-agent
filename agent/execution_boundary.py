"""Durable execution boundary primitives.

OpenHands-style runtime mining distilled for Hermes/AW Lite: decide whether a
piece of agent work can run in-process, in a tracked background job, or needs a
durable sandbox/workflow boundary. This module is policy metadata only; it does
not launch sandboxes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionBoundary(str, Enum):
    IN_PROCESS = "in_process"
    BACKGROUND_PROCESS = "background_process"
    DURABLE_WORKFLOW = "durable_workflow"
    SANDBOX_REQUIRED = "sandbox_required"


class WorkloadRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ExecutionProfile:
    boundary: ExecutionBoundary
    risk: WorkloadRisk
    reason: str
    require_workspace_isolation: bool = False
    require_persistent_evidence: bool = False
    require_network_off_by_default: bool = False


def classify_execution_boundary(
    *,
    modifies_repo: bool = False,
    runs_untrusted_code: bool = False,
    long_running: bool = False,
    needs_resume: bool = False,
    uses_network: bool = False,
    touches_secrets: bool = False,
    public_side_effect: bool = False,
) -> ExecutionProfile:
    """Classify the minimum safe execution boundary for an agent task."""
    if public_side_effect or touches_secrets or runs_untrusted_code:
        return ExecutionProfile(
            ExecutionBoundary.SANDBOX_REQUIRED,
            WorkloadRisk.HIGH,
            "untrusted code, secrets, or public side effects require isolated execution",
            require_workspace_isolation=True,
            require_persistent_evidence=True,
            require_network_off_by_default=True,
        )

    if modifies_repo and (long_running or needs_resume):
        return ExecutionProfile(
            ExecutionBoundary.DURABLE_WORKFLOW,
            WorkloadRisk.MEDIUM,
            "repo-changing long/resumable work belongs in AW Lite durable workflow state",
            require_workspace_isolation=False,
            require_persistent_evidence=True,
            require_network_off_by_default=uses_network,
        )

    if long_running or needs_resume:
        return ExecutionProfile(
            ExecutionBoundary.BACKGROUND_PROCESS,
            WorkloadRisk.MEDIUM,
            "long/resumable non-repo work needs tracked process/job evidence",
            require_persistent_evidence=True,
            require_network_off_by_default=uses_network,
        )

    return ExecutionProfile(
        ExecutionBoundary.IN_PROCESS,
        WorkloadRisk.LOW if not uses_network else WorkloadRisk.MEDIUM,
        "bounded local work can run in the current session",
        require_network_off_by_default=uses_network,
    )
