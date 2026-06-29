"""Async document parse job lifecycle primitives.

The model mirrors MinerU-style submit/status/result flows without running a
parser. It is deliberately serializable so Telegram/Bertus and AW jobs can track
large document processing outside a single chat turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class DocumentParseJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_REVIEW = "needs_review"


TERMINAL_STATUSES = {
    DocumentParseJobStatus.DONE,
    DocumentParseJobStatus.FAILED,
    DocumentParseJobStatus.CANCELLED,
    DocumentParseJobStatus.NEEDS_REVIEW,
}


@dataclass(frozen=True)
class DocumentParseFailure:
    kind: str
    message: str
    retryable: bool = False
    recommended_action: str | None = None

    def to_json(self) -> dict[str, Any]:
        return _compact(
            {
                "kind": self.kind,
                "message": self.message,
                "retryable": self.retryable,
                "recommended_action": self.recommended_action,
            }
        )


@dataclass(frozen=True)
class DocumentParseOutputs:
    markdown_ref: str | None = None
    blocks_jsonl_ref: str | None = None
    assets_jsonl_ref: str | None = None
    report_json_ref: str | None = None

    def to_json(self) -> dict[str, Any]:
        return _compact(
            {
                "markdown_ref": self.markdown_ref,
                "blocks_jsonl_ref": self.blocks_jsonl_ref,
                "assets_jsonl_ref": self.assets_jsonl_ref,
                "report_json_ref": self.report_json_ref,
            }
        )


@dataclass(frozen=True)
class DocumentParseJob:
    id: str
    source_ref: str
    backend: str
    status: DocumentParseJobStatus = DocumentParseJobStatus.QUEUED
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    progress: float = 0.0
    pages_seen: int = 0
    blocks_seen: int = 0
    tables_seen: int = 0
    assets_seen: int = 0
    low_confidence_blocks: int = 0
    warnings: tuple[str, ...] = ()
    outputs: DocumentParseOutputs = field(default_factory=DocumentParseOutputs)
    failure: DocumentParseFailure | None = None

    def to_json(self) -> dict[str, Any]:
        if not 0 <= self.progress <= 1:
            raise ValueError("progress must be between 0 and 1")
        return _compact(
            {
                "schema": "document.parse_job.v1",
                "id": self.id,
                "source_ref": self.source_ref,
                "backend": self.backend,
                "status": self.status.value,
                "submitted_at": self.submitted_at,
                "progress": self.progress,
                "pages_seen": self.pages_seen,
                "blocks_seen": self.blocks_seen,
                "tables_seen": self.tables_seen,
                "assets_seen": self.assets_seen,
                "low_confidence_blocks": self.low_confidence_blocks,
                "warnings": list(self.warnings) or None,
                "outputs": self.outputs.to_json() or None,
                "failure": self.failure.to_json() if self.failure else None,
            }
        )

    def transition(self, status: DocumentParseJobStatus, **updates: Any) -> "DocumentParseJob":
        if self.status in TERMINAL_STATUSES:
            raise ValueError(f"cannot transition terminal parse job {self.id} from {self.status.value}")
        next_job = replace(self, status=status, **updates)
        if status == DocumentParseJobStatus.RUNNING and next_job.progress == 0:
            next_job = replace(next_job, progress=0.01)
        if status in {DocumentParseJobStatus.DONE, DocumentParseJobStatus.NEEDS_REVIEW}:
            next_job = replace(next_job, progress=1.0)
        return next_job


def render_compact_status(job: DocumentParseJob) -> str:
    """Telegram/Bertus-friendly one-line status."""

    parts = [
        f"{job.status.value}",
        f"pages={job.pages_seen}",
        f"blocks={job.blocks_seen}",
        f"tables={job.tables_seen}",
        f"assets={job.assets_seen}",
        f"low_conf={job.low_confidence_blocks}",
    ]
    if job.warnings:
        parts.append(f"warnings={len(job.warnings)}")
    if job.failure:
        parts.append(f"failure={job.failure.kind}")
    return " · ".join(parts)


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, {}, [])}
