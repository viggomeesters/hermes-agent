"""Quality/debug artifacts for document parsing.

MinerU's layout and span visualizations are useful because they make extraction
quality inspectable. This module keeps that idea as lightweight metadata refs so
private page renders or crops can stay outside Git.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class QualityArtifactKind(str, Enum):
    PAGE_OVERLAY = "page_overlay"
    BLOCK_OVERLAY = "block_overlay"
    TABLE_PREVIEW = "table_preview"
    FORMULA_PREVIEW = "formula_preview"
    LOW_CONFIDENCE_CROP = "low_confidence_crop"


class ReviewSeverity(str, Enum):
    INFO = "info"
    WARN = "warn"
    BLOCKER = "blocker"


@dataclass(frozen=True)
class QualityArtifactRef:
    kind: QualityArtifactKind
    ref: str
    page: int | None = None
    block_id: str | None = None
    private: bool = True
    description: str | None = None

    def to_json(self) -> dict[str, Any]:
        return _compact(
            {
                "kind": self.kind.value,
                "ref": self.ref,
                "page": self.page,
                "block_id": self.block_id,
                "private": self.private,
                "description": self.description,
            }
        )


@dataclass(frozen=True)
class ReviewIssue:
    code: str
    severity: ReviewSeverity
    message: str
    page: int | None = None
    block_id: str | None = None
    evidence_ref: str | None = None

    def to_json(self) -> dict[str, Any]:
        return _compact(
            {
                "code": self.code,
                "severity": self.severity.value,
                "message": self.message,
                "page": self.page,
                "block_id": self.block_id,
                "evidence_ref": self.evidence_ref,
            }
        )


@dataclass(frozen=True)
class DocumentQualityReport:
    document_id: str
    pages_seen: int
    blocks_seen: int
    low_confidence_blocks: int = 0
    low_confidence_threshold: int = 1
    artifacts: tuple[QualityArtifactRef, ...] = ()
    issues: tuple[ReviewIssue, ...] = ()

    @property
    def needs_review(self) -> bool:
        return (
            self.low_confidence_blocks >= self.low_confidence_threshold
            or any(issue.severity in {ReviewSeverity.WARN, ReviewSeverity.BLOCKER} for issue in self.issues)
        )

    def to_json(self) -> dict[str, Any]:
        return _compact(
            {
                "schema": "document.quality_report.v1",
                "document_id": self.document_id,
                "pages_seen": self.pages_seen,
                "blocks_seen": self.blocks_seen,
                "low_confidence_blocks": self.low_confidence_blocks,
                "low_confidence_threshold": self.low_confidence_threshold,
                "needs_review": self.needs_review,
                "artifacts": [artifact.to_json() for artifact in self.artifacts] or None,
                "issues": [issue.to_json() for issue in self.issues] or None,
            }
        )


def summarize_quality(report: DocumentQualityReport) -> str:
    verdict = "needs_review" if report.needs_review else "ok"
    return (
        f"{verdict} · pages={report.pages_seen} · blocks={report.blocks_seen} · "
        f"low_conf={report.low_confidence_blocks} · artifacts={len(report.artifacts)} · issues={len(report.issues)}"
    )


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, {}, [])}
