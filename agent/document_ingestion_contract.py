"""JSONL-first document ingestion contract primitives.

Inspired by MinerU's document-to-Markdown/JSON/assets/report pipeline, but kept
backend-neutral and dependency-free for Hermes. These records are intended as a
stable machine-readable boundary between document parsers, vault views, and
agent context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class DocumentRecordType(str, Enum):
    SOURCE_DOCUMENT = "source_document"
    DOCUMENT_BLOCK = "document_block"
    DOCUMENT_ASSET = "document_asset"
    PARSE_REPORT = "parse_report"
    PARSE_WARNING = "parse_warning"
    REVIEW_DECISION = "review_decision"


class DocumentBlockKind(str, Enum):
    TITLE = "title"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    FORMULA = "formula"
    IMAGE = "image"
    LIST = "list"
    FOOTNOTE = "footnote"
    HEADER_FOOTER = "header_footer"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DocumentRegion:
    """Location of extracted content inside the original document."""

    page: int | None = None
    sheet: str | None = None
    slide: int | None = None
    bbox: tuple[float, float, float, float] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "page": self.page,
                "sheet": self.sheet,
                "slide": self.slide,
                "bbox": list(self.bbox) if self.bbox is not None else None,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class SourceDocumentRecord:
    id: str
    source_uri: str
    sha256: str
    media_type: str
    title: str | None = None
    private_payload_policy: Literal["metadata_only", "explicit_approval_required"] = (
        "metadata_only"
    )

    def to_json(self) -> dict[str, Any]:
        return _compact(
            {
                "record_type": DocumentRecordType.SOURCE_DOCUMENT.value,
                "id": self.id,
                "source_uri": self.source_uri,
                "sha256": self.sha256,
                "media_type": self.media_type,
                "title": self.title,
                "private_payload_policy": self.private_payload_policy,
            }
        )


@dataclass(frozen=True)
class DocumentBlockRecord:
    id: str
    document_id: str
    kind: DocumentBlockKind
    text: str
    reading_order: int
    region: DocumentRegion = field(default_factory=DocumentRegion)
    confidence: float | None = None
    backend: str | None = None
    source_sha256: str | None = None
    asset_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        return _compact(
            {
                "record_type": DocumentRecordType.DOCUMENT_BLOCK.value,
                "id": self.id,
                "document_id": self.document_id,
                "kind": self.kind.value,
                "text": self.text,
                "reading_order": self.reading_order,
                "region": self.region.to_json(),
                "confidence": self.confidence,
                "backend": self.backend,
                "source_sha256": self.source_sha256,
                "asset_ref": self.asset_ref,
                "metadata": self.metadata or None,
            }
        )


@dataclass(frozen=True)
class DocumentAssetRecord:
    id: str
    document_id: str
    kind: Literal["image", "table", "formula", "page_render", "debug_overlay"]
    media_ref: str
    region: DocumentRegion = field(default_factory=DocumentRegion)
    sha256: str | None = None
    caption: str | None = None

    def to_json(self) -> dict[str, Any]:
        return _compact(
            {
                "record_type": DocumentRecordType.DOCUMENT_ASSET.value,
                "id": self.id,
                "document_id": self.document_id,
                "kind": self.kind,
                "media_ref": self.media_ref,
                "region": self.region.to_json(),
                "sha256": self.sha256,
                "caption": self.caption,
            }
        )


@dataclass(frozen=True)
class ParseReportRecord:
    id: str
    document_id: str
    backend: str
    pages_seen: int
    blocks_seen: int
    assets_seen: int = 0
    low_confidence_blocks: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return _compact(
            {
                "record_type": DocumentRecordType.PARSE_REPORT.value,
                "id": self.id,
                "document_id": self.document_id,
                "backend": self.backend,
                "pages_seen": self.pages_seen,
                "blocks_seen": self.blocks_seen,
                "assets_seen": self.assets_seen,
                "low_confidence_blocks": self.low_confidence_blocks,
                "warnings": self.warnings or None,
            }
        )


def to_jsonl(records: list[Any]) -> str:
    """Serialize contract records to newline-delimited JSON."""

    import json

    return "".join(json.dumps(record.to_json(), ensure_ascii=False, sort_keys=True) + "\n" for record in records)


def _compact(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, {}, [])}
