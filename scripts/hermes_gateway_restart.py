#!/usr/bin/env python3
"""Serialize watchdog gateway restarts and retain machine-readable causes."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _append_event(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def request_restart(
    *, service: str, source: str, reason: str, state_dir: Path, force: bool = False
) -> int:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "gateway_restart.lock"
    events_path = state_dir / "gateway_restart_events.jsonl"
    request_id = str(uuid.uuid4())
    event = {
        "request_id": request_id,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "requester_pid": os.getpid(),
        "service": service,
        "source": source,
        "reason": reason,
    }
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            event["status"] = "deduplicated"
            _append_event(events_path, event)
            return 0
        try:
            commands = (
                [
                    ["systemctl", "--user", "kill", "--kill-who=all", "--signal=KILL", service],
                    ["systemctl", "--user", "reset-failed", service],
                    ["systemctl", "--user", "start", service],
                ]
                if force
                else [["systemctl", "--user", "restart", service]]
            )
            result = None
            for command in commands:
                result = subprocess.run(command, text=True, capture_output=True, timeout=240)
                if result.returncode:
                    break
            assert result is not None
            event["status"] = "requested" if result.returncode == 0 else "failed"
            event["returncode"] = result.returncode
            if result.returncode:
                event["error"] = (result.stderr or result.stdout or "unknown error").strip()[:500]
            _append_event(events_path, event)
            return result.returncode
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", default="hermes-gateway.service")
    parser.add_argument("--source", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "state",
    )
    args = parser.parse_args()
    return request_restart(
        service=args.service,
        source=args.source,
        reason=args.reason,
        state_dir=args.state_dir,
        force=args.force,
    )


if __name__ == "__main__":
    raise SystemExit(main())