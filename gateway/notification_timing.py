"""Timing primitives for visible long-running gateway notifications."""
from __future__ import annotations

from collections.abc import Iterator
import threading


def notification_delays(*, first_delay: float, interval: float) -> Iterator[float]:
    """Yield sleeps for a first deadline and turn-start-anchored heartbeats."""
    first = max(0.0, float(first_delay))
    recurring = max(0.0, float(interval))
    if recurring <= 0:
        if first > 0:
            yield first
        return
    if first <= 0 or first >= recurring:
        while True:
            yield recurring
    yield first
    yield recurring - first
    while True:
        yield recurring


class FirstProgressDeadline:
    """Thread-safe one-shot gate suppressed by any visible turn progress."""

    def __init__(self) -> None:
        self._visible = threading.Event()
        self._evaluated = threading.Event()

    def mark_visible(self) -> None:
        self._visible.set()

    def should_notify(self) -> bool:
        if self._evaluated.is_set():
            return False
        self._evaluated.set()
        return not self._visible.is_set()
