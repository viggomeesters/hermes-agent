import json
import time

from tools import process_registry as process_mod
from tools.process_registry import ProcessRegistry


def test_process_registry_exposes_monotonic_output_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(process_mod, "CHECKPOINT_PATH", tmp_path / "processes.json")
    registry = ProcessRegistry()
    session = registry.spawn_local(
        command="printf abc",
        cwd=str(tmp_path),
        task_id="progress-test",
        session_key="session-test",
    )

    completed = registry.wait(session.id, timeout=2)
    listed = registry.list_sessions(task_id="progress-test")
    item = next(row for row in listed if row["session_id"] == session.id)

    assert completed["status"] == "exited"
    assert item["output_chars_total"] >= 3
    assert item["last_output_at"] > 0


def test_progress_metrics_are_checkpointed_for_restart(monkeypatch, tmp_path):
    checkpoint = tmp_path / "processes.json"
    monkeypatch.setattr(process_mod, "CHECKPOINT_PATH", checkpoint)
    registry = ProcessRegistry()
    session = registry.spawn_local(
        command="python3 -c 'import time; print(\"x\", flush=True); time.sleep(1)'",
        cwd=str(tmp_path),
        task_id="progress-recovery-test",
        session_key="session-test",
    )
    try:
        deadline = time.monotonic() + 2.0
        while session.output_chars_total < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        registry._write_checkpoint()
        entry = next(
            row for row in json.loads(checkpoint.read_text())
            if row["session_id"] == session.id
        )
        assert entry["output_chars_total"] >= 2
        assert entry["last_output_at"] > 0
    finally:
        registry.kill_process(session.id, source="test.cleanup")
