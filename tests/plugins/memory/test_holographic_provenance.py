from __future__ import annotations

import json
import sqlite3

from plugins.memory.holographic import HolographicMemoryProvider
from plugins.memory.holographic.store import MemoryStore


def test_store_migrates_legacy_rows_without_inventing_source_provenance(tmp_path):
    database = tmp_path / "memory.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE facts (fact_id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL UNIQUE, category TEXT DEFAULT 'general', tags TEXT DEFAULT '', trust_score REAL DEFAULT 0.5, retrieval_count INTEGER DEFAULT 0, helpful_count INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, hrr_vector BLOB)"
    )
    connection.execute("INSERT INTO facts(content) VALUES ('Legacy fact')")
    connection.commit()
    connection.close()

    with MemoryStore(database) as store:
        row = store.list_facts(limit=10)[0]

    assert row["stable_id"].startswith("fact.holographic.")
    assert len(row["content_sha256"]) == 64
    assert row["provenance_quality"] == "legacy_unproven"
    assert row["source_ids"] == []
    assert row["review_status"] == "needs_review"


def test_add_fact_persists_machine_readable_provenance_and_stable_identity(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as store:
        fact_id = store.add_fact(
            "Queue admission is not a commit.",
            category="tool",
            tags="jsonl,writer",
            source_ids=["source.hermes.session.abc"],
            source_context={"session_id": "session-1", "message_id": "message-2"},
            review_status="accepted",
            provenance_quality="source_bound",
        )
        row = store.list_facts(limit=10)[0]

    assert row["fact_id"] == fact_id
    assert row["stable_id"].startswith("fact.holographic.")
    assert row["source_ids"] == ["source.hermes.session.abc"]
    assert row["source_context"]["message_id"] == "message-2"
    assert row["review_status"] == "accepted"
    assert row["lifecycle_status"] == "active"


def test_remove_is_a_retrieval_safe_forget_tombstone_not_a_hard_delete(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as store:
        fact_id = store.add_fact("Do not retrieve this after forget.")
        assert store.remove_fact(fact_id) is True
        assert store.search_facts("retrieve", min_trust=0.0) == []
        assert store.list_facts(min_trust=0.0) == []
        raw = store._conn.execute(
            "SELECT lifecycle_status, review_status, forgotten_at FROM facts WHERE fact_id = ?",
            (fact_id,),
        ).fetchone()

    assert raw["lifecycle_status"] == "forgotten"
    assert raw["review_status"] == "superseded"
    assert raw["forgotten_at"]


def test_provider_tool_add_binds_fact_to_current_session(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    provider = HolographicMemoryProvider(
        config={"db_path": str(tmp_path / "memory.db"), "auto_extract": False}
    )
    provider.initialize("session-provenance-1")

    response = json.loads(
        provider.handle_tool_call(
            "fact_store",
            {"action": "add", "content": "Remember source provenance."},
            message_id="message-77",
            chat_id="chat-5",
            thread_id="thread-8",
        )
    )
    row = provider._store.list_facts(limit=10)[0]

    assert response["status"] == "added"
    assert row["provenance_quality"] == "source_bound"
    assert row["source_context"] == {
        "chat_id": "chat-5",
        "message_id": "message-77",
        "session_id": "session-provenance-1",
        "thread_id": "thread-8",
    }
    assert len(row["source_ids"]) == 1
    assert row["source_ids"][0].startswith("source.hermes.session.")
    provider.shutdown()


def test_auto_extract_keeps_message_and_session_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    provider = HolographicMemoryProvider(
        config={"db_path": str(tmp_path / "memory.db"), "auto_extract": True}
    )
    provider.initialize("session-auto-1")
    provider.on_session_end([
        {"role": "user", "content": "I prefer deterministic memory rebuilds.", "id": "message-auto-9"}
    ])

    row = provider._store.list_facts(limit=10)[0]
    assert row["source_context"]["session_id"] == "session-auto-1"
    assert row["source_context"]["message_id"] == "message-auto-9"
    assert row["provenance_quality"] == "source_bound"
    provider.shutdown()
