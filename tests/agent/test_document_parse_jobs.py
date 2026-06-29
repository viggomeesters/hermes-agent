import pytest

from agent.document_parse_jobs import (
    DocumentParseFailure,
    DocumentParseJob,
    DocumentParseJobStatus,
    DocumentParseOutputs,
    render_compact_status,
)


def test_parse_job_starts_queued_with_source_and_backend():
    job = DocumentParseJob(id="job_1", source_ref="telegram://file/1", backend="mineru-pipeline")
    data = job.to_json()

    assert data["schema"] == "document.parse_job.v1"
    assert data["status"] == "queued"
    assert data["source_ref"] == "telegram://file/1"
    assert data["backend"] == "mineru-pipeline"


def test_running_transition_sets_nonzero_progress():
    job = DocumentParseJob(id="job_1", source_ref="file://a.pdf", backend="fast")
    running = job.transition(DocumentParseJobStatus.RUNNING, pages_seen=2)

    assert running.status == DocumentParseJobStatus.RUNNING
    assert running.progress > 0
    assert running.pages_seen == 2


def test_done_job_records_outputs_and_reaches_full_progress():
    job = DocumentParseJob(id="job_1", source_ref="file://a.pdf", backend="fast")
    done = job.transition(
        DocumentParseJobStatus.DONE,
        pages_seen=3,
        blocks_seen=20,
        outputs=DocumentParseOutputs(
            markdown_ref="run/doc.md",
            blocks_jsonl_ref="run/blocks.jsonl",
            report_json_ref="run/report.json",
        ),
    )

    data = done.to_json()
    assert data["status"] == "done"
    assert data["progress"] == 1.0
    assert data["outputs"]["blocks_jsonl_ref"] == "run/blocks.jsonl"


def test_failed_job_includes_retry_information():
    job = DocumentParseJob(id="job_1", source_ref="file://a.pdf", backend="remote")
    failed = job.transition(
        DocumentParseJobStatus.FAILED,
        failure=DocumentParseFailure(
            kind="backend_timeout",
            message="parser timed out",
            retryable=True,
            recommended_action="retry with local fast backend",
        ),
    )

    failure = failed.to_json()["failure"]
    assert failure["retryable"] is True
    assert failure["recommended_action"] == "retry with local fast backend"


def test_terminal_jobs_cannot_transition_again():
    job = DocumentParseJob(id="job_1", source_ref="file://a.pdf", backend="fast")
    done = job.transition(DocumentParseJobStatus.DONE)

    with pytest.raises(ValueError, match="terminal"):
        done.transition(DocumentParseJobStatus.RUNNING)


def test_compact_status_is_telegram_friendly():
    job = DocumentParseJob(
        id="job_1",
        source_ref="file://a.pdf",
        backend="fast",
        status=DocumentParseJobStatus.NEEDS_REVIEW,
        pages_seen=42,
        blocks_seen=300,
        tables_seen=8,
        assets_seen=12,
        low_confidence_blocks=5,
        warnings=("page_7_low_confidence",),
    )

    status = render_compact_status(job)
    assert status == "needs_review · pages=42 · blocks=300 · tables=8 · assets=12 · low_conf=5 · warnings=1"
