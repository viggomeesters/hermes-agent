# MinerU mining: async document parse jobs

MinerU exposes long-running parse work as a task lifecycle. Hermes needs the same shape for PDFs, Office files and images that cannot finish safely inside one Telegram turn.

Implemented in:

- `agent/document_parse_jobs.py`
- `tests/agent/test_document_parse_jobs.py`

## State machine

```text
queued → running → done
queued → running → needs_review
queued → running → failed
queued/running → cancelled
```

Terminal statuses cannot transition again:

- `done`
- `failed`
- `cancelled`
- `needs_review`

## Job record fields

Each parse job carries:

- `source_ref`: Telegram file ref, local path, vault ref, URL, or CAS ref;
- `backend`: selected parser adapter;
- `submitted_at`;
- `progress`;
- pages/blocks/tables/assets counts;
- low-confidence block count;
- warnings;
- output refs: Markdown, blocks JSONL, assets JSONL, report JSON;
- failure kind/message/retry guidance.

## Bertus status shape

Compact status is intentionally one line:

```text
needs_review · pages=42 · blocks=300 · tables=8 · assets=12 · low_conf=5 · warnings=1
```

That is enough for a Telegram response while the durable job JSON contains full refs and retry/debug fields.
