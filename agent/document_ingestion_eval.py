"""Evaluation helpers for document ingestion outputs.

The fixture model is public-safe metadata only. It scores parser outputs against
expected structural properties rather than storing real private documents in the
repository.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentEvalFixture:
    id: str
    description: str
    media_type: str
    fixture_ref: str
    expected_min_blocks: int = 1
    expected_tables: int = 0
    expected_assets: int = 0
    expected_warning_codes: tuple[str, ...] = ()
    public_safe: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "media_type": self.media_type,
            "fixture_ref": self.fixture_ref,
            "expected_min_blocks": self.expected_min_blocks,
            "expected_tables": self.expected_tables,
            "expected_assets": self.expected_assets,
            "expected_warning_codes": list(self.expected_warning_codes),
            "public_safe": self.public_safe,
        }


@dataclass(frozen=True)
class DocumentEvalObservation:
    fixture_id: str
    backend: str
    blocks_seen: int
    reading_order_ok: bool
    tables_seen: int = 0
    assets_seen: int = 0
    provenance_blocks: int = 0
    warning_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentEvalScorecard:
    fixture_id: str
    backend: str
    text_coverage: float
    reading_order: bool
    table_extraction: bool
    asset_extraction: bool
    provenance_coverage: float
    warning_match: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return (
            self.text_coverage >= 1.0
            and self.reading_order
            and self.table_extraction
            and self.asset_extraction
            and self.provenance_coverage >= 0.9
            and self.warning_match
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "backend": self.backend,
            "text_coverage": self.text_coverage,
            "reading_order": self.reading_order,
            "table_extraction": self.table_extraction,
            "asset_extraction": self.asset_extraction,
            "provenance_coverage": self.provenance_coverage,
            "warning_match": self.warning_match,
            "passed": self.passed,
            "notes": list(self.notes),
        }


def score_fixture(fixture: DocumentEvalFixture, observation: DocumentEvalObservation) -> DocumentEvalScorecard:
    text_coverage = observation.blocks_seen / max(fixture.expected_min_blocks, 1)
    provenance_coverage = observation.provenance_blocks / max(observation.blocks_seen, 1)
    expected_warnings = set(fixture.expected_warning_codes)
    observed_warnings = set(observation.warning_codes)
    notes: list[str] = []
    if not fixture.public_safe:
        notes.append("fixture must remain local-only and out of Git")
    if text_coverage < 1:
        notes.append("text coverage below expected minimum")
    if expected_warnings - observed_warnings:
        notes.append("missing expected warnings")

    return DocumentEvalScorecard(
        fixture_id=fixture.id,
        backend=observation.backend,
        text_coverage=round(text_coverage, 3),
        reading_order=observation.reading_order_ok,
        table_extraction=observation.tables_seen >= fixture.expected_tables,
        asset_extraction=observation.assets_seen >= fixture.expected_assets,
        provenance_coverage=round(provenance_coverage, 3),
        warning_match=expected_warnings.issubset(observed_warnings),
        notes=tuple(notes),
    )


def default_public_safe_fixtures() -> tuple[DocumentEvalFixture, ...]:
    return (
        DocumentEvalFixture("scanned-page", "synthetic scanned one-page letter", "image/png", "fixtures/document-ingestion/scanned-page.json", expected_min_blocks=3, expected_assets=1, expected_warning_codes=("ocr_used",)),
        DocumentEvalFixture("table-heavy-pdf", "synthetic PDF with two tables", "application/pdf", "fixtures/document-ingestion/table-heavy-pdf.json", expected_min_blocks=8, expected_tables=2),
        DocumentEvalFixture("multi-column-doc", "synthetic multi-column article", "application/pdf", "fixtures/document-ingestion/multi-column-doc.json", expected_min_blocks=6),
        DocumentEvalFixture("chart-image-page", "synthetic chart/image page", "application/pdf", "fixtures/document-ingestion/chart-image-page.json", expected_min_blocks=2, expected_assets=1),
        DocumentEvalFixture("office-proxy", "synthetic Office document proxy", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "fixtures/document-ingestion/office-proxy.json", expected_min_blocks=4),
    )
