#!/usr/bin/env python3
"""Collect and summarize bounded Hermes gateway reliability soak evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser()
DEFAULT_OUTPUT = DEFAULT_HOME / "audits" / "hermes-gateway-soak" / "samples.jsonl"
ERROR_PATTERNS = {
    "pool_exhaustion": ("Pool timeout", "connection pool are occupied"),
    "pair_integrity": ("pair-integrity", "pair integrity"),
    "telegram_conflict": ("Conflict: terminated by other getUpdates", "Telegram conflict"),
    "provider_error": ("provider pool", "All providers failed", "No available provider"),
}


def parse_key_values(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def _run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _cgroup_metrics(control_group: str) -> dict[str, int]:
    root = Path("/sys/fs/cgroup") / control_group.lstrip("/")
    result = {"memory_anon": 0, "memory_file": 0, "oom": 0, "oom_kill": 0}
    try:
        for line in (root / "memory.stat").read_text().splitlines():
            key, value = line.split()
            if key == "anon":
                result["memory_anon"] = _int(value)
            elif key == "file":
                result["memory_file"] = _int(value)
    except Exception:
        pass
    try:
        for line in (root / "memory.events").read_text().splitlines():
            key, value = line.split()
            if key in {"oom", "oom_kill"}:
                result[key] = _int(value)
    except Exception:
        pass
    return result


def _journal_error_counts(service: str, since: str) -> dict[str, int]:
    cp = _run(["journalctl", "--user", "-u", service, "--since", since, "--no-pager", "-o", "cat"])
    text = cp.stdout if cp.returncode == 0 else ""
    return {
        name: sum(text.lower().count(pattern.lower()) for pattern in patterns)
        for name, patterns in ERROR_PATTERNS.items()
    }


def collect(service: str, hermes_home: Path) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc)
    props = [
        "ActiveState", "SubState", "MainPID", "NRestarts", "MemoryCurrent",
        "MemoryPeak", "TasksCurrent", "ControlGroup", "Result", "ExecMainStatus",
    ]
    cp = _run(["systemctl", "--user", "show", service, *(f"-p{name}" for name in props)])
    service_state = parse_key_values(cp.stdout)
    gateway_state = _read_json(hermes_home / "gateway_state.json")
    telegram = (gateway_state.get("platforms") or {}).get("telegram") or {}
    telegram_updated = telegram.get("updated_at")
    heartbeat_age: float | None = None
    if telegram_updated:
        try:
            heartbeat_age = max(
                0.0,
                (timestamp - datetime.fromisoformat(str(telegram_updated).replace("Z", "+00:00"))).total_seconds(),
            )
        except (TypeError, ValueError):
            pass
    sample: dict[str, Any] = {
        "timestamp": timestamp.isoformat(),
        "service": service,
        "active_state": service_state.get("ActiveState"),
        "sub_state": service_state.get("SubState"),
        "pid": _int(service_state.get("MainPID")),
        "gateway_state_pid": _int(gateway_state.get("pid")),
        "n_restarts": _int(service_state.get("NRestarts")),
        "memory_current": _int(service_state.get("MemoryCurrent")),
        "memory_peak": _int(service_state.get("MemoryPeak")),
        "tasks_current": _int(service_state.get("TasksCurrent")),
        "result": service_state.get("Result"),
        "exec_main_status": _int(service_state.get("ExecMainStatus")),
        "telegram_state": telegram.get("state"),
        "telegram_heartbeat_age_seconds": heartbeat_age,
        "errors": _journal_error_counts(service, "2 minutes ago"),
    }
    sample.update(_cgroup_metrics(service_state.get("ControlGroup", "")))
    sample["pid_generation_matches"] = sample["pid"] == sample["gateway_state_pid"]
    return sample


def append_sample(output: Path, sample: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a") as handle:
        handle.write(json.dumps(sample, sort_keys=True) + "\n")


def summarize(samples_path: Path, minimum_hours: float = 24) -> dict[str, Any]:
    rows = []
    if samples_path.exists():
        for line in samples_path.read_text().splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
            except json.JSONDecodeError:
                continue
    if not rows:
        return {"passed": False, "failures": ["no_samples"], "sample_count": 0}

    first = datetime.fromisoformat(rows[0]["timestamp"].replace("Z", "+00:00"))
    last = datetime.fromisoformat(rows[-1]["timestamp"].replace("Z", "+00:00"))
    duration_hours = (last - first).total_seconds() / 3600
    lineage: list[int] = []
    for row in rows:
        pid = _int(row.get("pid"))
        if pid and (not lineage or lineage[-1] != pid):
            lineage.append(pid)
    error_totals: Counter[str] = Counter()
    for row in rows:
        error_totals.update({key: _int(value) for key, value in (row.get("errors") or {}).items()})
    restart_delta = max(0, _int(rows[-1].get("n_restarts")) - _int(rows[0].get("n_restarts")))
    failures: list[str] = []
    if duration_hours < minimum_hours:
        failures.append(f"duration_lt_{minimum_hours:g}h")
    if restart_delta or len(lineage) > 1:
        failures.append("unexpected_restart")
    if any(error_totals.values()):
        failures.append("forbidden_errors")
    if any(_int(row.get("oom_kill")) for row in rows):
        failures.append("oom_kill")
    if any(row.get("pid_generation_matches") is False for row in rows):
        failures.append("pid_generation_mismatch")
    return {
        "passed": not failures,
        "failures": failures,
        "sample_count": len(rows),
        "duration_hours": round(duration_hours, 3),
        "pid_lineage": lineage,
        "restart_delta": restart_delta,
        "error_totals": dict(error_totals),
        "max_memory_anon": max(_int(row.get("memory_anon")) for row in rows),
        "max_memory_file": max(_int(row.get("memory_file")) for row in rows),
        "max_tasks": max(_int(row.get("tasks_current")) for row in rows),
        "max_telegram_heartbeat_age_seconds": max(
            (float(row["telegram_heartbeat_age_seconds"]) for row in rows if row.get("telegram_heartbeat_age_seconds") is not None),
            default=None,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", default="hermes-gateway.service")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--minimum-hours", type=float, default=24)
    args = parser.parse_args()
    if args.summary:
        result = summarize(args.output, args.minimum_hours)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["passed"] else 1
    sample = collect(args.service, DEFAULT_HOME)
    append_sample(args.output, sample)
    print(json.dumps(sample, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())