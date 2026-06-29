# MinerU mining: Bertus document capture route

This is the Telegram command-bus boundary for document uploads. It is intentionally pure classification/rendering: no download, no vault write, no remote parser call.

Implemented in:

- `agent/document_capture_route.py`
- `tests/gateway/test_document_capture_route.py`

## Route decisions

| Decision | Meaning |
|---|---|
| `ignore` | Unsupported file type. |
| `create_parse_job` | Supported upload; create a private/local-first parse job. |
| `require_approval` | A remote/API parser was requested for a private file; wait for explicit approval. |

## Supported default inputs

- PDF
- PNG/JPEG
- DOCX/PPTX/XLSX MIME types

## Safe defaults

- Private/local first.
- Remote/API parser requires explicit approval for sensitive/private uploads.
- Upload classification creates parse-job intent only; it does not treat the upload as durable vault truth.
- Response shape stays Telegram-compact:

```text
Result: ...
Evidence: ...
Validation: ...
Changed: ...
Open: ...
```

This prepares Bertus for document ingestion without adding a broad automatic vault-write path.
