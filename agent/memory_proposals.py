"""Memory provenance and conflict primitives.

Mined from Mem0/Graphiti-style memory systems: store proposals with source
provenance, detect likely contradictions, and promote only reviewed facts. This
module is deterministic and local; it does not call an LLM or write durable
memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Iterable


class MemoryProposalStatus(str, Enum):
    PROPOSED = "proposed"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class MemoryProvenance:
    source_uri: str
    excerpt_hash: str
    observed_at: str

    @classmethod
    def from_excerpt(cls, source_uri: str, excerpt: str, observed_at: str) -> "MemoryProvenance":
        return cls(source_uri=source_uri, excerpt_hash=sha256(excerpt.encode("utf-8")).hexdigest(), observed_at=observed_at)


@dataclass(frozen=True)
class MemoryProposal:
    subject: str
    predicate: str
    value: str
    provenance: MemoryProvenance
    status: MemoryProposalStatus = MemoryProposalStatus.PROPOSED

    @property
    def key(self) -> tuple[str, str]:
        return (self.subject.casefold().strip(), self.predicate.casefold().strip())


def find_memory_conflicts(
    proposal: MemoryProposal,
    existing: Iterable[MemoryProposal],
) -> list[MemoryProposal]:
    """Return promoted/proposed facts with same subject+predicate and different value."""
    conflicts: list[MemoryProposal] = []
    proposal_value = proposal.value.casefold().strip()
    for fact in existing:
        if fact.status in {MemoryProposalStatus.REJECTED, MemoryProposalStatus.SUPERSEDED}:
            continue
        if fact.key == proposal.key and fact.value.casefold().strip() != proposal_value:
            conflicts.append(fact)
    return conflicts


def should_auto_promote(proposal: MemoryProposal, existing: Iterable[MemoryProposal]) -> bool:
    """Allow deterministic promotion only when no same-key conflict exists."""
    return not find_memory_conflicts(proposal, existing)
