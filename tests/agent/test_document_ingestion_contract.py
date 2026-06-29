import json

import pytest

from agent.document_ingestion_contract import (
    DocumentAssetRecord,
    DocumentBlockKind,
    DocumentBlockRecord,
    DocumentRegion,
    ParseReportRecord,
    SourceDocumentRecord,
    to_jsonl,
)


def test_source_document_keeps_private_payload_metadata_only():
    record = SourceDocumentRecord(
        id="doc_1",
        source_uri="file://private/example.pdf",
        sha256="abc123",
        media_type="application/pdf",
        title="Example",
    ).to_json()

    assert record["record_type"] == "source_document"
    assert record["private_payload_policy"] == "metadata_only"
    assert "payload" not in record


def test_document_block_carries_reading_order_region_and_provenance():
    record = DocumentBlockRecord(
        id="block_1",
        document_id="doc_1",
        kind=DocumentBlockKind.TABLE,
        text="<table><tr><td>A</td></tr></table>",
        reading_order=7,
        region=DocumentRegion(page=2, bbox=(1.0, 2.0, 3.0, 4.0)),
        confidence=0.91,
        backend="mineru-pipeline",
        source_sha256="abc123",
        asset_ref="cas://table-crop",
    ).to_json()

    assert record["record_type"] == "document_block"
    assert record["kind"] == "table"
    assert record["reading_order"] == 7
    assert record["region"] == {"page": 2, "bbox": [1.0, 2.0, 3.0, 4.0]}
    assert record["backend"] == "mineru-pipeline"
    assert record["source_sha256"] == "abc123"


def test_document_asset_uses_reference_not_embedded_binary():
    record = DocumentAssetRecord(
        id="asset_1",
        document_id="doc_1",
        kind="image",
        media_ref="cas://sha256/deadbeef",
        region=DocumentRegion(page=3),
        sha256="deadbeef",
    ).to_json()

    assert record["record_type"] == "document_asset"
    assert record["media_ref"].startswith("cas://")
    assert "bytes" not in record
    assert "base64" not in record


def test_parse_report_surfaces_low_confidence_and_warnings():
    report = ParseReportRecord(
        id="report_1",
        document_id="doc_1",
        backend="mineru-vlm",
        pages_seen=10,
        blocks_seen=93,
        assets_seen=8,
        low_confidence_blocks=3,
        warnings=["page_7_low_confidence"],
    ).to_json()

    assert report["record_type"] == "parse_report"
    assert report["low_confidence_blocks"] == 3
    assert report["warnings"] == ["page_7_low_confidence"]


def test_jsonl_serialization_is_one_json_object_per_line():
    jsonl = to_jsonl([
        SourceDocumentRecord(id="doc_1", source_uri="file://a.pdf", sha256="abc", media_type="application/pdf"),
        ParseReportRecord(id="report_1", document_id="doc_1", backend="fast", pages_seen=1, blocks_seen=2),
    ])

    lines = jsonl.splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["record_type"] for line in lines] == ["source_document", "parse_report"]


def test_confidence_must_be_normalized():
    with pytest.raises(ValueError, match="confidence"):
        DocumentBlockRecord(
            id="block_bad",
            document_id="doc_1",
            kind=DocumentBlockKind.PARAGRAPH,
            text="x",
            reading_order=1,
            confidence=1.5,
        ).to_json()
