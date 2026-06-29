from agent.document_ingestion_eval import (
    DocumentEvalFixture,
    DocumentEvalObservation,
    default_public_safe_fixtures,
    score_fixture,
)


def test_default_fixture_manifest_is_public_safe_metadata_only():
    fixtures = default_public_safe_fixtures()

    assert len(fixtures) == 5
    assert all(fixture.public_safe for fixture in fixtures)
    assert all("private" not in fixture.fixture_ref for fixture in fixtures)
    assert {fixture.id for fixture in fixtures} == {
        "scanned-page",
        "table-heavy-pdf",
        "multi-column-doc",
        "chart-image-page",
        "office-proxy",
    }


def test_scorecard_reports_text_and_provenance_coverage():
    fixture = DocumentEvalFixture("basic", "basic", "application/pdf", "fixtures/basic.json", expected_min_blocks=10)
    score = score_fixture(
        fixture,
        DocumentEvalObservation(
            fixture_id="basic",
            backend="fast",
            blocks_seen=8,
            reading_order_ok=True,
            provenance_blocks=6,
        ),
    )

    assert score.text_coverage == 0.8
    assert score.provenance_coverage == 0.75
    assert score.passed is False
    assert "text coverage below expected minimum" in score.notes


def test_table_and_asset_expectations_are_scored():
    fixture = DocumentEvalFixture(
        "tables",
        "tables",
        "application/pdf",
        "fixtures/tables.json",
        expected_min_blocks=2,
        expected_tables=2,
        expected_assets=1,
    )
    score = score_fixture(
        fixture,
        DocumentEvalObservation(
            fixture_id="tables",
            backend="precision",
            blocks_seen=2,
            reading_order_ok=True,
            tables_seen=2,
            assets_seen=1,
            provenance_blocks=2,
        ),
    )

    assert score.table_extraction is True
    assert score.asset_extraction is True
    assert score.passed is True


def test_warning_expectations_require_expected_codes():
    fixture = DocumentEvalFixture(
        "scan",
        "scan",
        "image/png",
        "fixtures/scan.json",
        expected_warning_codes=("ocr_used",),
    )
    missing = score_fixture(
        fixture,
        DocumentEvalObservation("scan", "ocr", blocks_seen=1, reading_order_ok=True, provenance_blocks=1),
    )
    matched = score_fixture(
        fixture,
        DocumentEvalObservation(
            "scan",
            "ocr",
            blocks_seen=1,
            reading_order_ok=True,
            provenance_blocks=1,
            warning_codes=("ocr_used",),
        ),
    )

    assert missing.warning_match is False
    assert "missing expected warnings" in missing.notes
    assert matched.warning_match is True


def test_private_real_vault_fixture_is_marked_local_only():
    fixture = DocumentEvalFixture(
        "real-vault-benchmark",
        "private real vault dry-run",
        "application/pdf",
        "local-only://vault/sample.pdf",
        public_safe=False,
    )
    score = score_fixture(
        fixture,
        DocumentEvalObservation("real-vault-benchmark", "local", blocks_seen=1, reading_order_ok=True, provenance_blocks=1),
    )

    assert "fixture must remain local-only and out of Git" in score.notes
