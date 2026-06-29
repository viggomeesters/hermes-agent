"""Backend-neutral document parser adapter descriptors.

MinerU exposes multiple parsing modes (pipeline, VLM, hybrid and HTTP clients).
Hermes keeps that as an optional adapter boundary: describe capabilities and
select a safe backend without importing heavy parser dependencies into core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class ParserExecutionMode(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class ParserQualityMode(str, Enum):
    FAST = "fast"
    PRECISION = "precision"
    VISION = "vision"


class ParserRiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ParserCapabilities:
    ocr: bool = False
    tables: bool = False
    formulas: bool = False
    images: bool = False
    layout: bool = False
    office: bool = False

    def covers(self, required: "ParserCapabilities") -> bool:
        return all(
            getattr(self, field_name) or not getattr(required, field_name)
            for field_name in ("ocr", "tables", "formulas", "images", "layout", "office")
        )


@dataclass(frozen=True)
class DocumentParserDescriptor:
    name: str
    execution: ParserExecutionMode
    quality: ParserQualityMode
    input_formats: tuple[str, ...]
    output_formats: tuple[str, ...]
    capabilities: ParserCapabilities
    risk_tier: ParserRiskTier
    requires_explicit_approval_for_private_docs: bool = False
    optional_dependency: str | None = None

    def supports_format(self, media_type: str) -> bool:
        return media_type in self.input_formats or "*/*" in self.input_formats


@dataclass(frozen=True)
class DocumentParseRequest:
    media_type: str
    private: bool = True
    pages: int | None = None
    expected_tables: bool = False
    expected_formulas: bool = False
    expected_images: bool = False
    scanned_or_image: bool = False
    allow_remote: bool = False

    @property
    def required_capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(
            ocr=self.scanned_or_image,
            tables=self.expected_tables,
            formulas=self.expected_formulas,
            images=self.expected_images,
            layout=True,
            office=self.media_type
            in {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        )


@dataclass(frozen=True)
class ParserSelection:
    descriptor: DocumentParserDescriptor | None
    allowed: bool
    reason: str


def select_document_parser(
    request: DocumentParseRequest,
    descriptors: Iterable[DocumentParserDescriptor],
) -> ParserSelection:
    """Choose the safest capable parser for a document request."""

    required = request.required_capabilities
    candidates: list[DocumentParserDescriptor] = []
    blocked_remote: DocumentParserDescriptor | None = None
    for descriptor in descriptors:
        if not descriptor.supports_format(request.media_type):
            continue
        if not descriptor.capabilities.covers(required):
            continue
        if descriptor.execution == ParserExecutionMode.REMOTE:
            if request.private and descriptor.requires_explicit_approval_for_private_docs:
                if not request.allow_remote:
                    blocked_remote = descriptor
                    continue
            if not request.allow_remote:
                continue
        candidates.append(descriptor)

    if not candidates:
        if blocked_remote is not None:
            return ParserSelection(
                descriptor=None,
                allowed=False,
                reason=f"remote parser {blocked_remote.name} requires explicit approval for private documents",
            )
        return ParserSelection(None, False, f"no parser supports {request.media_type} with required capabilities")

    candidates.sort(key=_selection_rank)
    chosen = candidates[0]
    return ParserSelection(chosen, True, f"selected {chosen.name}")


def mineru_optional_descriptor() -> DocumentParserDescriptor:
    """Describe MinerU as an optional external parser wrapper, not a core dep."""

    return DocumentParserDescriptor(
        name="mineru-pipeline",
        execution=ParserExecutionMode.LOCAL,
        quality=ParserQualityMode.PRECISION,
        input_formats=("application/pdf", "image/png", "image/jpeg"),
        output_formats=("text/markdown", "application/jsonl", "application/json"),
        capabilities=ParserCapabilities(ocr=True, tables=True, formulas=True, images=True, layout=True),
        risk_tier=ParserRiskTier.MEDIUM,
        optional_dependency="mineru[core]",
    )


def _selection_rank(descriptor: DocumentParserDescriptor) -> tuple[int, int]:
    execution_rank = 0 if descriptor.execution == ParserExecutionMode.LOCAL else 1
    quality_rank = {
        ParserQualityMode.FAST: 0,
        ParserQualityMode.PRECISION: 1,
        ParserQualityMode.VISION: 2,
    }[descriptor.quality]
    return (execution_rank, quality_rank)
