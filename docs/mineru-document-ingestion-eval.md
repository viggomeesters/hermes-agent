# MinerU mining: document ingestion eval corpus

MinerU's issue/debug culture points to a useful habit: parser changes need sample documents and measurable extraction expectations. Hermes should keep those samples public-safe and metadata-only by default.

Implemented in:

- `agent/document_ingestion_eval.py`
- `tests/agent/test_document_ingestion_eval.py`

## Public-safe fixture classes

The default manifest covers five synthetic fixture types:

1. scanned page;
2. table-heavy PDF;
3. multi-column document;
4. chart/image page;
5. Office document proxy.

Fixture records are metadata refs, not private payloads. Real vault benchmarks use `local-only://...` and must remain out of Git.

## Scorecard dimensions

A backend scorecard reports:

- text coverage;
- reading-order sanity;
- table extraction presence;
- asset extraction presence;
- provenance coverage;
- expected warning matches.

This lets future MinerU, marker, pymupdf, OCR, or API backends be compared against the same JSONL contract.

## Private benchmark rule

Private real-vault documents may be used only as local dry-run benchmarks. Store aggregate scorecards or metadata, never the raw file, OCR dump, page render, or crop in Git without explicit approval.
