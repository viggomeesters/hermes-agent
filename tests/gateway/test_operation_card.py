from gateway.operation_card import (
    ProgressContext,
    ProgressSnapshot,
    ProgressTracker,
    collect_progress_snapshot,
    register_progress_provider,
    render_operation_card,
    unregister_progress_provider,
)
from tools import process_registry as process_mod
from tools.process_registry import ProcessRegistry


def _sample(*, now, current, total=100, phase="import", worker="proc_1 · PID 42"):
    return ProgressSnapshot(
        phase=phase,
        current=current,
        total=total,
        unit="records",
        worker_id=worker,
        sampled_at=now,
        started_at=0,
    )


def test_positive_delta_computes_rate_and_eta():
    tracker = ProgressTracker(stall_after=60)
    tracker.observe(_sample(now=10, current=20))

    view = tracker.observe(_sample(now=20, current=40))

    assert view.delta == 20
    assert view.rate == 2
    assert view.eta_seconds == 30
    assert view.stalled is False


def test_zero_delta_becomes_stalled_after_freshness_window_even_with_live_worker():
    tracker = ProgressTracker(stall_after=60)
    tracker.observe(_sample(now=0, current=10))

    fresh = tracker.observe(_sample(now=30, current=10))
    stale = tracker.observe(_sample(now=61, current=10))

    assert fresh.stalled is False
    assert stale.stalled is True
    assert stale.worker_id == "proc_1 · PID 42"
    assert "geen meetbare voortgang" in render_operation_card(stale)


def test_counter_reset_never_reports_negative_progress_or_false_stall():
    tracker = ProgressTracker(stall_after=60)
    tracker.observe(_sample(now=10, current=80))

    view = tracker.observe(_sample(now=20, current=5))

    assert view.counter_reset is True
    assert view.delta is None
    assert view.rate is None
    assert view.eta_seconds is None
    assert view.stalled is False


def test_missing_total_keeps_measured_delta_but_eta_unknown():
    tracker = ProgressTracker(stall_after=60)
    tracker.observe(_sample(now=10, current=5, total=None))

    view = tracker.observe(_sample(now=20, current=15, total=None))
    card = render_operation_card(view)

    assert view.delta == 10
    assert view.rate == 1
    assert view.eta_seconds is None
    assert "ETA: onbekend" in card
    assert "Fase: import" in card
    assert "Worker: proc_1 · PID 42" in card


def test_registered_structured_provider_wins_and_can_be_unregistered():
    expected = _sample(now=50, current=25, phase="custom phase", worker="unit-7")
    register_progress_provider("test-provider", lambda context: expected, priority=1)
    try:
        assert collect_progress_snapshot(ProgressContext(session_key="s")) == expected
    finally:
        unregister_progress_provider("test-provider")

    fallback = collect_progress_snapshot(
        ProgressContext(fallback_phase="fallback", fallback_worker="agent:s")
    )
    assert fallback.phase == "fallback"


def test_compact_final_card_states_cover_success_failure_and_stop():
    tracker = ProgressTracker(stall_after=60)
    base = _sample(now=10, current=100)

    success = tracker.observe(ProgressSnapshot(**{**base.__dict__, "status": "completed"}))
    failed = tracker.observe(ProgressSnapshot(**{**base.__dict__, "status": "failed", "sampled_at": 11}))
    stopped = tracker.observe(ProgressSnapshot(**{**base.__dict__, "status": "interrupted", "sampled_at": 12}))

    assert "Status: ✅ afgerond" in render_operation_card(success)
    assert "Status: 🔴 mislukt" in render_operation_card(failed)
    assert "Status: ⏹ gestopt" in render_operation_card(stopped)


def test_builtin_process_provider_exposes_pid_bound_monotonic_counter(monkeypatch, tmp_path):
    monkeypatch.setattr(process_mod, "CHECKPOINT_PATH", tmp_path / "processes.json")
    registry = ProcessRegistry()
    monkeypatch.setattr(process_mod, "process_registry", registry)
    session = registry.spawn_local(
        command="sleep 1",
        cwd=str(tmp_path),
        task_id="card-process",
        session_key="card-session",
    )
    try:
        snapshot = collect_progress_snapshot(
            ProgressContext(task_id="card-process", session_key="card-session")
        )
        assert snapshot.phase == "background process"
        assert snapshot.current == 0
        assert snapshot.unit == "output chars"
        assert session.id in snapshot.worker_id
        assert f"PID {session.pid}" in snapshot.worker_id
    finally:
        registry.kill_process(session.id, source="test.cleanup")
