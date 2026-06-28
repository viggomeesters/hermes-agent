"""Minimal agent evaluation trajectory primitives.

Mined from mini-swe-agent and terminal benchmark patterns: keep a linear,
auditable trajectory and score it against explicit checks. This module is local
metadata only; it does not upload telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time


class TrajectoryEventKind(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    VERIFY = "verify"
    DECISION = "decision"


@dataclass(frozen=True)
class TrajectoryEvent:
    kind: TrajectoryEventKind
    message: str
    timestamp: float = field(default_factory=time)


@dataclass(frozen=True)
class EvalCheck:
    name: str
    passed: bool
    evidence: str


@dataclass(frozen=True)
class EvalVerdict:
    passed: bool
    score: float
    failed_checks: tuple[str, ...]


def append_event(trajectory: tuple[TrajectoryEvent, ...], kind: TrajectoryEventKind | str, message: str) -> tuple[TrajectoryEvent, ...]:
    """Append an event without rewriting prior trajectory history."""
    return (*trajectory, TrajectoryEvent(TrajectoryEventKind(kind), message))


def grade_checks(checks: list[EvalCheck]) -> EvalVerdict:
    """Grade explicit checks as a simple pass ratio."""
    if not checks:
        return EvalVerdict(False, 0.0, ("no checks",))
    failed = tuple(check.name for check in checks if not check.passed)
    score = (len(checks) - len(failed)) / len(checks)
    return EvalVerdict(not failed, score, failed)
