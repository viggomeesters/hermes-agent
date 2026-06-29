# MinerU mining: JSONL document ingestion contract

Source inspected: `opendatalab/MinerU` at `/tmp/mineru-inspect`, commit `3e60291`.

MinerU's valuable pattern is not its model stack. The useful primitive is its output boundary:

```text
document input → markdown view + structured JSON + extracted assets + parse report
```

Hermes should keep that boundary backend-neutral and JSONL-first.

## Contract records

| Record | Purpose |
|---|---|
| `source_document` | Metadata for the original file/URL/upload, including `sha256` and media type. |
| `document_block` | Reading-order text/table/formula/image block with region/provenance fields. |
| `document_asset` | Reference to extracted private assets via CAS/local refs, not embedded payload. |
| `parse_report` | Backend, page/block/asset counts, warnings, low-confidence totals. |
| `parse_warning` | Future append-only warning event for page/block-level extraction issues. |
| `review_decision` | Future human/agent review decision before promotion into vault truth. |

## Privacy boundary

Do not put raw private document bytes, screenshots, crops, base64 payloads, or full OCR dumps in Git by default. Canonical JSONL may reference private content through `media_ref` / CAS paths, plus source hash and provenance.

## Provenance fields

Every `document_block` should be able to carry:

- source document id;
- source hash;
- page/sheet/slide;
- optional bounding box;
- reading order;
- extractor backend;
- confidence;
- asset reference when the block came from a crop/table/formula/image.

## Dual output rule

Use both outputs deliberately:

```text
*.blocks.jsonl  → canonical machine-readable context
*.md            → generated human view for Obsidian/review
*.assets.jsonl  → private asset references
*.report.json   → parse status and quality evidence
```

The Markdown view is not the source of truth. It is a view over JSONL records.

## Implementation slice

Implemented in:

- `agent/document_ingestion_contract.py`
- `tests/agent/test_document_ingestion_contract.py`

This slice intentionally avoids MinerU dependencies and model code. It is an artifact contract that later parser adapters can target.
