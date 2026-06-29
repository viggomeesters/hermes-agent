# MinerU mining: parser adapter interface

MinerU's useful architecture is multi-backend parsing:

| MinerU mode | Hermes interpretation |
|---|---|
| pipeline | local/fast-or-precision parser |
| VLM | high-cost vision parser |
| hybrid | precision parser with layout awareness |
| HTTP client | remote parser requiring explicit privacy approval |

Hermes should not import MinerU as a core dependency. Instead, parsers expose descriptors:

- input formats;
- output formats;
- local vs remote execution;
- quality mode;
- capabilities: OCR, tables, formulas, images, layout, Office;
- risk tier;
- explicit approval requirement for private documents;
- optional dependency or wrapper name.

Implemented in:

- `agent/document_parser_adapters.py`
- `tests/agent/test_document_parser_adapters.py`

## Selection rules

Safe default:

```text
private document + capable local parser → local parser
private document + only remote parser → block unless allow_remote=True
unsupported format → diagnostic, not fallback hallucination
```

This preserves MinerU's backend flexibility without turning Hermes core into a heavy OCR/runtime bundle.
