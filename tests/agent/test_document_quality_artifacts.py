from agent.document_quality_artifacts import (
    DocumentQualityReport,
    QualityArtifactKind,
    QualityArtifactRef,
    ReviewIssue,
    ReviewSeverity,
    summarize_quality,
)


def test_artifact_refs_do_not_embed_private_images():
    artifact = QualityArtifactRef(
        kind=QualityArtifactKind.PAGE_OVERLAY,
        ref="cas://private/page-1-overlay.png",
        page=1,
        private=True,
        description="layout overlay",
    ).to_json()

    assert artifact["ref"].startswith("cas://")
    assert artifact["private"] is True
    assert "bytes" not in artifact
    assert "base64" not in artifact


def test_low_confidence_blocks_trigger_needs_review():
    report = DocumentQualityReport(
        document_id="doc_1",
        pages_seen=5,
        blocks_seen=80,
        low_confidence_blocks=2,
        low_confidence_threshold=1,
    )

    assert report.needs_review is True
    assert report.to_json()["needs_review"] is True


def test_warning_issue_triggers_needs_review_with_evidence_ref():
    report = DocumentQualityReport(
        document_id="doc_1",
        pages_seen=3,
        blocks_seen=20,
        issues=(
            ReviewIssue(
                code="table_structure_uncertain",
                severity=ReviewSeverity.WARN,
                message="table columns may be misaligned",
                page=2,
                evidence_ref="cas://private/table-preview",
            ),
        ),
    )

    data = report.to_json()
    assert data["needs_review"] is True
    assert data["issues"][0]["evidence_ref"] == "cas://private/table-preview"


def test_info_only_report_can_be_ok():
    report = DocumentQualityReport(
        document_id="doc_1",
        pages_seen=1,
        blocks_seen=4,
        issues=(ReviewIssue(code="small_doc", severity=ReviewSeverity.INFO, message="short document"),),
    )

    assert report.needs_review is False


def test_summary_is_compact_for_telegram():
    report = DocumentQualityReport(
        document_id="doc_1",
        pages_seen=42,
        blocks_seen=300,
        low_confidence_blocks=3,
        artifacts=(QualityArtifactRef(kind=QualityArtifactKind.TABLE_PREVIEW, ref="cas://t", page=7),),
    )

    assert summarize_quality(report) == "needs_review · pages=42 · blocks=300 · low_conf=3 · artifacts=1 · issues=0"
