from agent.memory_proposals import (
    MemoryProposal,
    MemoryProposalStatus,
    MemoryProvenance,
    find_memory_conflicts,
    should_auto_promote,
)


def provenance(source="vault://note", excerpt="Viggo prefers Dutch", observed="2026-06-28"):
    return MemoryProvenance.from_excerpt(source, excerpt, observed)


def test_provenance_hash_is_stable_without_storing_excerpt():
    first = provenance(excerpt="same")
    second = provenance(excerpt="same")

    assert first.excerpt_hash == second.excerpt_hash
    assert first.excerpt_hash != "same"


def test_same_subject_predicate_different_value_conflicts():
    old = MemoryProposal("Viggo", "timezone", "CET", provenance(), MemoryProposalStatus.PROMOTED)
    new = MemoryProposal("viggo", "Timezone", "PST", provenance())

    assert find_memory_conflicts(new, [old]) == [old]
    assert should_auto_promote(new, [old]) is False


def test_rejected_or_superseded_facts_do_not_block_promotion():
    old = MemoryProposal("Viggo", "timezone", "CET", provenance(), MemoryProposalStatus.SUPERSEDED)
    new = MemoryProposal("viggo", "Timezone", "PST", provenance())

    assert find_memory_conflicts(new, [old]) == []
    assert should_auto_promote(new, [old]) is True


def test_same_value_does_not_conflict():
    old = MemoryProposal("Viggo", "prefers_language", "Dutch", provenance(), MemoryProposalStatus.PROMOTED)
    new = MemoryProposal("viggo", "Prefers_Language", " dutch ", provenance())

    assert find_memory_conflicts(new, [old]) == []
