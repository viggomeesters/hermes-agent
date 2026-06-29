from agent.document_capture_route import (
    CaptureDecision,
    IncomingDocument,
    classify_document_capture,
    render_capture_response,
)
from agent.document_parse_jobs import DocumentParseJob, DocumentParseJobStatus


def test_pdf_upload_routes_to_local_parse_job_without_vault_truth():
    route = classify_document_capture(
        IncomingDocument(platform="telegram", file_ref="tg://file/1", media_type="application/pdf", filename="brief.pdf")
    )

    assert route.decision == CaptureDecision.CREATE_PARSE_JOB
    assert route.request.media_type == "application/pdf"
    assert route.request.private is True
    assert route.changed == ("parse_job",)


def test_image_upload_uses_vision_mode_and_scanned_request():
    route = classify_document_capture(
        IncomingDocument(platform="telegram", file_ref="tg://photo/1", media_type="image/jpeg", filename="scan.jpg")
    )

    assert route.decision == CaptureDecision.CREATE_PARSE_JOB
    assert route.parser_mode == "vision"
    assert route.request.scanned_or_image is True


def test_table_caption_routes_to_precision_with_table_expectation():
    route = classify_document_capture(
        IncomingDocument(
            platform="telegram",
            file_ref="tg://file/2",
            media_type="application/pdf",
            filename="report.pdf",
            caption="haal de tabellen eruit",
        )
    )

    assert route.parser_mode == "precision"
    assert route.request.expected_tables is True


def test_remote_private_parser_requires_explicit_approval():
    route = classify_document_capture(
        IncomingDocument(platform="telegram", file_ref="tg://file/1", media_type="application/pdf"),
        allow_remote=True,
    )

    assert route.decision == CaptureDecision.REQUIRE_APPROVAL
    assert route.request is None
    assert "explicit approval" in route.reason


def test_unsupported_file_is_ignored():
    route = classify_document_capture(
        IncomingDocument(platform="telegram", file_ref="tg://file/1", media_type="video/mp4")
    )

    assert route.decision == CaptureDecision.IGNORE
    assert "unsupported" in route.reason


def test_capture_response_uses_result_evidence_validation_changed_open_shape():
    route = classify_document_capture(
        IncomingDocument(platform="telegram", file_ref="tg://file/1", media_type="application/pdf")
    )
    job = DocumentParseJob(
        id="job_1",
        source_ref="tg://file/1",
        backend="local-fast",
        status=DocumentParseJobStatus.QUEUED,
    )

    response = render_capture_response(route, job)
    assert response.splitlines()[0] == "Result: create_parse_job"
    assert "Evidence: local/private-first" in response
    assert "Validation: queued" in response
    assert "Changed: parse_job" in response
    assert response.endswith("Open: none")
