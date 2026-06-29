from agent.document_parser_adapters import (
    DocumentParseRequest,
    DocumentParserDescriptor,
    ParserCapabilities,
    ParserExecutionMode,
    ParserQualityMode,
    ParserRiskTier,
    mineru_optional_descriptor,
    select_document_parser,
)


def descriptor(name, *, execution=ParserExecutionMode.LOCAL, quality=ParserQualityMode.FAST, caps=None, formats=("application/pdf",), approval=False):
    return DocumentParserDescriptor(
        name=name,
        execution=execution,
        quality=quality,
        input_formats=formats,
        output_formats=("application/jsonl", "text/markdown"),
        capabilities=caps or ParserCapabilities(layout=True),
        risk_tier=ParserRiskTier.LOW,
        requires_explicit_approval_for_private_docs=approval,
    )


def test_local_fast_fallback_is_preferred_for_simple_private_pdf():
    result = select_document_parser(
        DocumentParseRequest(media_type="application/pdf", private=True),
        [
            descriptor("remote-vlm", execution=ParserExecutionMode.REMOTE, quality=ParserQualityMode.VISION, approval=True),
            descriptor("local-fast", quality=ParserQualityMode.FAST),
        ],
    )

    assert result.allowed is True
    assert result.descriptor.name == "local-fast"


def test_precision_backend_selected_when_tables_required():
    result = select_document_parser(
        DocumentParseRequest(media_type="application/pdf", expected_tables=True),
        [
            descriptor("local-fast", caps=ParserCapabilities(layout=True)),
            descriptor("local-precision", quality=ParserQualityMode.PRECISION, caps=ParserCapabilities(layout=True, tables=True)),
        ],
    )

    assert result.allowed is True
    assert result.descriptor.name == "local-precision"


def test_remote_private_document_requires_explicit_approval():
    result = select_document_parser(
        DocumentParseRequest(media_type="application/pdf", expected_formulas=True, private=True, allow_remote=False),
        [
            descriptor(
                "remote-vlm",
                execution=ParserExecutionMode.REMOTE,
                quality=ParserQualityMode.VISION,
                caps=ParserCapabilities(layout=True, formulas=True),
                approval=True,
            )
        ],
    )

    assert result.allowed is False
    assert "explicit approval" in result.reason


def test_remote_private_document_can_be_selected_after_approval():
    result = select_document_parser(
        DocumentParseRequest(media_type="application/pdf", expected_formulas=True, private=True, allow_remote=True),
        [
            descriptor(
                "remote-vlm",
                execution=ParserExecutionMode.REMOTE,
                quality=ParserQualityMode.VISION,
                caps=ParserCapabilities(layout=True, formulas=True),
                approval=True,
            )
        ],
    )

    assert result.allowed is True
    assert result.descriptor.name == "remote-vlm"


def test_unsupported_format_reports_diagnostic():
    result = select_document_parser(
        DocumentParseRequest(media_type="video/mp4"),
        [descriptor("local-fast", formats=("application/pdf",))],
    )

    assert result.allowed is False
    assert "no parser supports video/mp4" in result.reason


def test_mineru_is_optional_external_descriptor():
    mineru = mineru_optional_descriptor()

    assert mineru.name == "mineru-pipeline"
    assert mineru.optional_dependency == "mineru[core]"
    assert mineru.capabilities.tables is True
    assert mineru.execution == ParserExecutionMode.LOCAL
