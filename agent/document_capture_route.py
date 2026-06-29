"""Bertus command-bus routing for document uploads.

This module is a small pure classifier/renderer. It does not download files,
write the vault, or call remote parsers. Platform adapters can use it to decide
whether an uploaded Telegram file/photo should become a document parse job and
which safety gate applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from agent.document_parse_jobs import DocumentParseJob, render_compact_status
from agent.document_parser_adapters import DocumentParseRequest


class CaptureDecision(str, Enum):
    IGNORE = "ignore"
    CREATE_PARSE_JOB = "create_parse_job"
    REQUIRE_APPROVAL = "require_approval"


SUPPORTED_DOCUMENT_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True)
class IncomingDocument:
    platform: str
    file_ref: str
    media_type: str
    filename: str | None = None
    caption: str | None = None
    private: bool = True
    size_bytes: int | None = None


@dataclass(frozen=True)
class CaptureRoute:
    decision: CaptureDecision
    reason: str
    request: DocumentParseRequest | None = None
    parser_mode: str = "fast"
    changed: tuple[str, ...] = ()


def classify_document_capture(upload: IncomingDocument, *, allow_remote: bool = False) -> CaptureRoute:
    if upload.media_type not in SUPPORTED_DOCUMENT_TYPES:
        return CaptureRoute(CaptureDecision.IGNORE, f"unsupported media type: {upload.media_type}")

    caption = (upload.caption or "").lower()
    filename = (upload.filename or "").lower()
    table_heavy = any(token in caption for token in ("tabel", "table", "xlsx", "spreadsheet"))
    formula_heavy = any(token in caption for token in ("formule", "formula", "latex"))
    scanned_or_image = upload.media_type.startswith("image/") or "scan" in caption
    office = Path(filename).suffix in {".docx", ".pptx", ".xlsx"}
    mode = "precision" if table_heavy or formula_heavy or office else "fast"
    if scanned_or_image:
        mode = "vision"

    if upload.private and allow_remote:
        return CaptureRoute(
            CaptureDecision.REQUIRE_APPROVAL,
            "remote/API parser for private uploads requires explicit approval",
            parser_mode=mode,
        )

    request = DocumentParseRequest(
        media_type=upload.media_type,
        private=upload.private,
        expected_tables=table_heavy or filename.endswith(".xlsx"),
        expected_formulas=formula_heavy,
        expected_images=scanned_or_image,
        scanned_or_image=scanned_or_image,
        allow_remote=False,
    )
    return CaptureRoute(
        CaptureDecision.CREATE_PARSE_JOB,
        "local/private-first document parse job",
        request=request,
        parser_mode=mode,
        changed=("parse_job",),
    )


def render_capture_response(route: CaptureRoute, job: DocumentParseJob | None = None) -> str:
    result = route.decision.value
    evidence = route.reason
    validation = render_compact_status(job) if job else "not_started"
    changed = ", ".join(route.changed) if route.changed else "none"
    open_item = "approve remote parser" if route.decision == CaptureDecision.REQUIRE_APPROVAL else "none"
    return (
        f"Result: {result}\n"
        f"Evidence: {evidence}\n"
        f"Validation: {validation}\n"
        f"Changed: {changed}\n"
        f"Open: {open_item}"
    )
