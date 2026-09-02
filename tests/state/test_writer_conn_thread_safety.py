"""Regression coverage for shared SessionDB writer-connection races (#99502)."""

import threading
import time

import pytest

from hermes_state import SessionDB


@pytest.fixture
def db(tmp_path):
    database = SessionDB(db_path=tmp_path / "state.db")
    try:
        yield database
    finally:
        database.close()


def _hammer(db: SessionDB, reader, *, duration_s: float = 0.5) -> list[tuple[str, str]]:
    session_id = db.create_session("race-session", "test")
    errors: list[tuple[str, str]] = []
    stop = threading.Event()

    def writer() -> None:
        index = 0
        while not stop.is_set():
            try:
                db.append_message(session_id, "user", f"message-{index}")
                index += 1
            except Exception as exc:  # noqa: BLE001 - assertion captures all races
                errors.append((type(exc).__name__, str(exc)))
                stop.set()

    def read_loop() -> None:
        while not stop.is_set():
            try:
                reader(db, session_id)
            except Exception as exc:  # noqa: BLE001 - assertion captures all races
                errors.append((type(exc).__name__, str(exc)))
                stop.set()

    threads = [threading.Thread(target=writer)] + [
        threading.Thread(target=read_loop) for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline and not stop.is_set():
        time.sleep(0.01)
    stop.set()
    for thread in threads:
        thread.join(timeout=5)
    return errors


@pytest.mark.parametrize(
    "reader",
    [
        lambda db, session_id: db.get_compression_lock_holder(session_id),
        lambda db, session_id: db.get_handoff_state(session_id),
        lambda db, _session_id: db.list_pending_handoffs(),
    ],
)
def test_formerly_unlocked_readers_do_not_race_writer(db, reader) -> None:
    assert _hammer(db, reader) == []


def test_post_commit_maintenance_system_error_does_not_replay_message(
    db, monkeypatch
) -> None:
    db.create_session("exactly-once", "test")
    before = db._write_count
    maintenance_calls = {"count": 0}

    def fail_after_commit(*, max_pages):
        maintenance_calls["count"] += 1
        raise SystemError(
            "<TrackedConnection object at 0x0> returned NULL without setting an exception"
        )

    monkeypatch.setattr(db, "_FTS_MERGE_EVERY_N_WRITES", 1)
    monkeypatch.setattr(db, "_merge_fts_incrementally", fail_after_commit)

    message_id = db.append_message("exactly-once", "user", "one durable row")
    matching = [
        row
        for row in db.get_messages("exactly-once")
        if row["content"] == "one durable row"
    ]

    assert isinstance(message_id, int)
    assert len(matching) == 1
    assert db.get_session("exactly-once")["message_count"] == 1
    assert db._write_count == before + 1
    assert maintenance_calls["count"] == 1
