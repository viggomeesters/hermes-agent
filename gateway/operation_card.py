"""Structured progress snapshots and compact editable operation cards."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import math
import threading
import time
from typing import Callable, Optional


@dataclass(frozen=True)
class ProgressContext:
    session_key: str = ""
    task_id: str = ""
    fallback_phase: str = "agent actief"
    fallback_worker: str = "agent"


@dataclass(frozen=True)
class ProgressSnapshot:
    phase: str
    current: Optional[float] = None
    total: Optional[float] = None
    unit: str = "items"
    worker_id: str = "agent"
    sampled_at: Optional[float] = None
    started_at: Optional[float] = None
    status: str = "running"


@dataclass(frozen=True)
class ProgressView(ProgressSnapshot):
    delta: Optional[float] = None
    rate: Optional[float] = None
    eta_seconds: Optional[float] = None
    stalled: bool = False
    counter_reset: bool = False
    seconds_since_change: Optional[float] = None


class ProgressTracker:
    def __init__(self, *, stall_after: float = 600.0):
        self.stall_after = max(0.0, float(stall_after))
        self.previous: Optional[ProgressSnapshot] = None
        self.last_change_at: Optional[float] = None

    def observe(self, snapshot: ProgressSnapshot) -> ProgressView:
        now = time.time() if snapshot.sampled_at is None else float(snapshot.sampled_at)
        snapshot = replace(snapshot, sampled_at=now)
        previous = self.previous
        same_counter = bool(
            previous
            and previous.current is not None
            and snapshot.current is not None
            and previous.worker_id == snapshot.worker_id
            and previous.unit == snapshot.unit
        )
        delta = rate = eta = None
        reset = False

        if self.last_change_at is None and snapshot.current is not None:
            baseline = snapshot.started_at if snapshot.started_at is not None else now
            self.last_change_at = min(now, float(baseline))

        if same_counter:
            raw_delta = float(snapshot.current) - float(previous.current)
            elapsed = now - float(previous.sampled_at)
            if raw_delta < 0:
                reset = True
                self.last_change_at = now
            else:
                delta = raw_delta
                if raw_delta > 0:
                    self.last_change_at = now
                    if elapsed > 0:
                        rate = raw_delta / elapsed
                        if (
                            snapshot.total is not None
                            and rate > 0
                            and float(snapshot.total) >= float(snapshot.current)
                        ):
                            eta = (float(snapshot.total) - float(snapshot.current)) / rate
        elif snapshot.current is not None and previous is not None:
            self.last_change_at = now

        seconds_since_change = None
        stalled = False
        if snapshot.current is not None and self.last_change_at is not None:
            seconds_since_change = max(0.0, now - self.last_change_at)
            stalled = (
                snapshot.status == "running"
                and self.stall_after > 0
                and seconds_since_change >= self.stall_after
            )

        self.previous = snapshot
        return ProgressView(
            **snapshot.__dict__,
            delta=delta,
            rate=rate,
            eta_seconds=eta,
            stalled=stalled,
            counter_reset=reset,
            seconds_since_change=seconds_since_change,
        )


Provider = Callable[[ProgressContext], Optional[ProgressSnapshot]]
_PROVIDERS: list[tuple[int, str, Provider]] = []
_PROVIDER_LOCK = threading.Lock()


def register_progress_provider(name: str, provider: Provider, *, priority: int = 100) -> None:
    """Register a structured progress provider; lower priority runs first."""
    with _PROVIDER_LOCK:
        _PROVIDERS[:] = [entry for entry in _PROVIDERS if entry[1] != name]
        _PROVIDERS.append((int(priority), str(name), provider))
        _PROVIDERS.sort(key=lambda entry: (entry[0], entry[1]))


def unregister_progress_provider(name: str) -> None:
    with _PROVIDER_LOCK:
        _PROVIDERS[:] = [entry for entry in _PROVIDERS if entry[1] != name]


def _process_snapshot(context: ProgressContext) -> Optional[ProgressSnapshot]:
    try:
        from tools.process_registry import process_registry

        sessions = process_registry.list_sessions(
            task_id=context.task_id or None,
            session_key=context.session_key or None,
        )
    except Exception:
        return None
    running = [item for item in sessions if item.get("status") == "running"]
    if not running:
        return None
    session = min(running, key=lambda item: int(item.get("uptime_seconds") or 0))
    sampled_at = time.time()
    started_at = sampled_at - float(session.get("uptime_seconds") or 0)
    pid = session.get("pid")
    worker = str(session.get("session_id") or "process")
    if pid:
        worker += f" · PID {pid}"
    return ProgressSnapshot(
        phase="background process",
        current=float(session.get("output_chars_total") or 0),
        total=None,
        unit="output chars",
        worker_id=worker,
        sampled_at=sampled_at,
        started_at=started_at,
        status="running",
    )


def collect_progress_snapshot(context: ProgressContext) -> ProgressSnapshot:
    with _PROVIDER_LOCK:
        providers = list(_PROVIDERS)
    for _, _, provider in providers:
        try:
            snapshot = provider(context)
        except Exception:
            continue
        if isinstance(snapshot, ProgressSnapshot):
            return snapshot
    process_snapshot = _process_snapshot(context)
    if process_snapshot is not None:
        return process_snapshot
    return ProgressSnapshot(
        phase=context.fallback_phase or "agent actief",
        worker_id=context.fallback_worker or "agent",
        sampled_at=time.time(),
        status="running",
    )


def _number(value: float) -> str:
    if math.isfinite(value) and float(value).is_integer():
        return f"{int(value):,}".replace(",", ".")
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _duration(seconds: Optional[float]) -> str:
    if seconds is None or not math.isfinite(seconds):
        return "onbekend"
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, remainder = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s" if remainder else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}u {minutes}m" if minutes else f"{hours}u"


def render_operation_card(view: ProgressView, *, updated_at: Optional[datetime] = None) -> str:
    status = "🔴 geen meetbare voortgang" if view.stalled else "🟢 actief"
    if view.status in {"failed", "error"}:
        status = "🔴 mislukt"
    elif view.status in {"completed", "done", "exited"}:
        status = "✅ afgerond"
    elif view.status in {"cancelled", "canceled", "stopped", "interrupted"}:
        status = "⏹ gestopt"

    if view.current is None:
        progress = "onbekend"
    elif view.total is None:
        progress = f"{_number(float(view.current))} {view.unit}"
    else:
        progress = (
            f"{_number(float(view.current))}/{_number(float(view.total))} {view.unit}"
        )
    if view.delta is not None:
        progress += f" · +{_number(float(view.delta))} sinds vorige meting"
    elif view.counter_reset:
        progress += " · teller opnieuw gestart"

    lines = [
        "⚙️ Operatie",
        f"Status: {status}",
        f"Fase: {view.phase or 'onbekend'}",
        f"Voortgang: {progress}",
        f"ETA: {_duration(view.eta_seconds)}",
        f"Worker: {view.worker_id or 'onbekend'}",
    ]
    if view.stalled and view.seconds_since_change is not None:
        lines.append(f"Geen delta: {_duration(view.seconds_since_change)}")
    clock = updated_at or datetime.now().astimezone()
    lines.append(f"Bijgewerkt: {clock:%H:%M:%S}")
    return "\n".join(lines)
