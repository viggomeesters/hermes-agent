from agent.execution_boundary import (
    ExecutionBoundary,
    WorkloadRisk,
    classify_execution_boundary,
)


def test_bounded_local_work_runs_in_process():
    profile = classify_execution_boundary()

    assert profile.boundary is ExecutionBoundary.IN_PROCESS
    assert profile.risk is WorkloadRisk.LOW


def test_repo_changing_resumable_work_uses_durable_workflow():
    profile = classify_execution_boundary(modifies_repo=True, long_running=True)

    assert profile.boundary is ExecutionBoundary.DURABLE_WORKFLOW
    assert profile.require_persistent_evidence is True


def test_untrusted_code_requires_sandbox_with_network_off_default():
    profile = classify_execution_boundary(runs_untrusted_code=True, uses_network=True)

    assert profile.boundary is ExecutionBoundary.SANDBOX_REQUIRED
    assert profile.risk is WorkloadRisk.HIGH
    assert profile.require_workspace_isolation is True
    assert profile.require_network_off_by_default is True


def test_long_running_non_repo_work_uses_background_process_boundary():
    profile = classify_execution_boundary(long_running=True)

    assert profile.boundary is ExecutionBoundary.BACKGROUND_PROCESS
    assert profile.require_persistent_evidence is True
