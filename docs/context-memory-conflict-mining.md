# Mem0/Graphiti/Cognee mining: context-memory conflict model

Sources inspected:

| Source | Evidence |
|---|---|
| Mem0 search/docs results | memory add pipeline extracts facts, checks conflicts, inserts or updates; conflict handling is explicit |
| Graphiti search/docs results | temporal graph keeps episodes/provenance; old facts are invalidated/superseded rather than silently deleted |
| Existing Hermes memory/fact-store behavior | Hermes has memory, fact_store, session_search and vault boundaries; do not broadly ingest vault into memory |

## What to steal

The useful primitive is **proposal before canonical memory**:

1. raw source remains source of truth;
2. extracted fact is a proposal with provenance;
3. same subject+predicate with different value is a conflict, not an overwrite;
4. promoted facts can later be superseded without losing the source trail;
5. broad vault ingestion is avoided; bounded source subsets create proposals.

## Hermes/vault translation

| Memory pattern | Hermes boundary |
|---|---|
| Mem0 extraction/update cycle | Use proposals before durable memory/fact mutation |
| Graphiti episodes | Vault note/session/tool output remains source episode/provenance |
| Conflict edges | Detect same-key different-value facts before promotion |
| Temporal truth | Supersede facts instead of deleting history silently |
| Graph retrieval | Use bounded context providers, not full vault import |

## Implemented slice

Added `agent.memory_proposals`:

- `MemoryProvenance.from_excerpt(source_uri, excerpt, observed_at)` stores source URI and excerpt hash;
- `MemoryProposal(subject, predicate, value, provenance, status)`;
- `find_memory_conflicts(proposal, existing)`;
- `should_auto_promote(proposal, existing)`.

This is intentionally deterministic and local. It does not call an LLM and does not mutate Hermes memory. It gives future memory/vault pipelines a safe skeleton for proposal/conflict/promotion behavior.

## Policy

| Situation | Action |
|---|---|
| same subject+predicate+same value | no conflict |
| same subject+predicate+different value | conflict; no auto-promotion |
| old fact superseded/rejected | does not block new proposal |
| source excerpt needed | store source URI + hash; do not dump raw private source into memory |

## What not to copy

- broad automatic vault ingestion;
- LLM memory writes with no proposal review;
- deleting old facts without supersession trail;
- treating vector similarity as truth;
- storing raw private excerpts in generic memory by default.

## Future follow-up

- Add a local proposal queue for vault-derived facts if/when a concrete pipeline needs it.
- Add source readback before promotion for user/profile facts.
- Link proposals to `fact_store` only after conflict review.
