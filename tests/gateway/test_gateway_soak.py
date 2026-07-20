import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "hermes_gateway_soak.py"


def load_module():
    spec = importlib.util.spec_from_file_location("hermes_gateway_soak", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_parse_key_values_keeps_embedded_equals():
    soak = load_module()
    assert soak.parse_key_values("MainPID=42\nStatusText=a=b\n") == {
        "MainPID": "42",
        "StatusText": "a=b",
    }


def test_summarize_flags_pid_changes_and_forbidden_errors(tmp_path):
    soak = load_module()
    samples = tmp_path / "samples.jsonl"
    rows = [
        {
            "timestamp": "2026-07-20T00:00:00+00:00",
            "pid": 10,
            "n_restarts": 0,
            "telegram_heartbeat_age_seconds": 2,
            "errors": {"pool_exhaustion": 0, "pair_integrity": 0, "telegram_conflict": 0},
            "oom_kill": 0,
        },
        {
            "timestamp": "2026-07-21T00:00:00+00:00",
            "pid": 11,
            "n_restarts": 1,
            "telegram_heartbeat_age_seconds": 4,
            "errors": {"pool_exhaustion": 1, "pair_integrity": 0, "telegram_conflict": 0},
            "oom_kill": 0,
        },
    ]
    samples.write_text("".join(json.dumps(row) + "\n" for row in rows))

    summary = soak.summarize(samples, minimum_hours=24)

    assert summary["duration_hours"] == 24
    assert summary["pid_lineage"] == [10, 11]
    assert summary["restart_delta"] == 1
    assert summary["error_totals"]["pool_exhaustion"] == 1
    assert summary["passed"] is False


def test_summarize_requires_full_window(tmp_path):
    soak = load_module()
    samples = tmp_path / "samples.jsonl"
    rows = [
        {"timestamp": "2026-07-20T00:00:00+00:00", "pid": 10, "n_restarts": 0, "errors": {}, "oom_kill": 0},
        {"timestamp": "2026-07-20T23:59:00+00:00", "pid": 10, "n_restarts": 0, "errors": {}, "oom_kill": 0},
    ]
    samples.write_text("".join(json.dumps(row) + "\n" for row in rows))

    summary = soak.summarize(samples, minimum_hours=24)

    assert summary["passed"] is False
    assert "duration_lt_24h" in summary["failures"]