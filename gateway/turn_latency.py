from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_TURNS: dict[tuple[str, str, str], dict[str, Any]] = {}
_MAX_BYTES = 5 * 1024 * 1024


def _key(source: Any, message_id: Any) -> tuple[str, str, str]:
    platform = getattr(getattr(source, "platform", None), "value", None)
    return (
        str(platform or getattr(source, "platform", "unknown")),
        str(getattr(source, "chat_id", "unknown")),
        str(message_id or "unknown"),
    )


def begin_turn(source: Any, message_id: Any) -> None:
    now = time.monotonic()
    with _LOCK:
        _TURNS[_key(source, message_id)] = {
            "schema": "hermes.turn-latency.v1",
            "turn_id": uuid.uuid4().hex,
            "platform": str(getattr(getattr(source, "platform", None), "value", "unknown")),
            "received_at": datetime.now(timezone.utc).isoformat(),
            "_started": now,
        }


def mark_turn_phase(source: Any, message_id: Any, phase: str) -> None:
    if phase not in {"ack", "first_progress"}:
        return
    with _LOCK:
        row = _TURNS.get(_key(source, message_id))
        if row is None:
            return
        field = f"{phase}_ms"
        row.setdefault(field, round((time.monotonic() - row["_started"]) * 1000))


def finish_turn(source: Any, message_id: Any, outcome: str, *, home: Path | None = None) -> None:
    with _LOCK:
        row = _TURNS.pop(_key(source, message_id), None)
    if row is None:
        return
    row["total_ms"] = round((time.monotonic() - row.pop("_started")) * 1000)
    row["outcome"] = str(outcome)
    root = home or Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    path = root / "logs" / "turn-latency.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size >= _MAX_BYTES:
        rotated = path.with_suffix(path.suffix + ".1")
        if rotated.exists():
            rotated.unlink()
        path.replace(rotated)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
