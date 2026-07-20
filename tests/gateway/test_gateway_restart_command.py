import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock


SCRIPT = Path(__file__).parents[2] / "scripts" / "hermes_gateway_restart.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_gateway_restart", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_restart_writes_machine_readable_reason(tmp_path, monkeypatch):
    restart = load_module()
    completed = MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(restart.subprocess, "run", MagicMock(return_value=completed))

    result = restart.request_restart(
        service="hermes-gateway.service",
        source="resource-watchdog",
        reason="MemoryAnonCurrent exceeded",
        state_dir=tmp_path,
    )

    event = json.loads((tmp_path / "gateway_restart_events.jsonl").read_text().splitlines()[-1])
    assert result == 0
    assert event["source"] == "resource-watchdog"
    assert event["reason"] == "MemoryAnonCurrent exceeded"
    assert event["status"] == "requested"


def test_restart_lock_prevents_stacked_requests(tmp_path, monkeypatch):
    restart = load_module()
    lock_path = tmp_path / "gateway_restart.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    held = lock_path.open("a+")
    restart.fcntl.flock(held.fileno(), restart.fcntl.LOCK_EX | restart.fcntl.LOCK_NB)
    run = MagicMock()
    monkeypatch.setattr(restart.subprocess, "run", run)
    try:
        result = restart.request_restart(
            service="hermes-gateway.service",
            source="telegram-pool-watchdog",
            reason="pool timeout",
            state_dir=tmp_path,
        )
    finally:
        restart.fcntl.flock(held.fileno(), restart.fcntl.LOCK_UN)
        held.close()

    assert result == 0
    run.assert_not_called()
    event = json.loads((tmp_path / "gateway_restart_events.jsonl").read_text().splitlines()[-1])
    assert event["status"] == "deduplicated"