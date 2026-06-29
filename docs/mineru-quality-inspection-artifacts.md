# MinerU mining: quality inspection artifacts

MinerU's layout/span visualizations matter because OCR output can look plausible while being wrong. Hermes needs the same evidence pattern without storing private page images in Git.

Implemented in:

- `agent/document_quality_artifacts.py`
- `tests/agent/test_document_quality_artifacts.py`

## Artifact model

Quality artifacts are references, not payloads:

- `page_overlay`
- `block_overlay`
- `table_preview`
- `formula_preview`
- `low_confidence_crop`

Each artifact stores `ref`, optional page/block id, privacy flag, and description. The `ref` can point to a private CAS/local artifact outside Git.

## Review model

A parse result can contain review issues:

- `info`: useful note, not review-blocking;
- `warn`: needs review;
- `blocker`: cannot promote into canonical vault truth.

`needs_review` becomes true when low-confidence blocks cross the threshold or a warning/blocker issue exists.

This prevents the bad pattern: OCR succeeded technically, so the agent silently treats it as truth.
