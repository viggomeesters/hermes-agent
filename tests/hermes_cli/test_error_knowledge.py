from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hermes_cli.error_knowledge import (
    default_db_path,
    export_jsonl,
    incident_stats,
    list_incidents,
    record_incident,
    resolve_incident,
    search_incidents,
)


def test_default_path_follows_active_hermes_profile(tmp_path, monkeypatch):
    first = tmp_path / "profile-a"
    second = tmp_path / "profile-b"

    monkeypatch.setenv("HERMES_HOME", str(first))
    assert default_db_path() == first / "state" / "error-knowledge" / "errors.sqlite3"
    record_incident(source="test", component="gateway", signature="delivery failed")

    monkeypatch.setenv("HERMES_HOME", str(second))
    assert default_db_path() == second / "state" / "error-knowledge" / "errors.sqlite3"
    assert incident_stats()["incidents"] == {}

    monkeypatch.setenv("HERMES_HOME", str(first))
    assert incident_stats()["incidents"] == {"open": 1}


def test_record_deduplicates_and_resolved_incident_reopens_as_regressed(tmp_path):
    db = tmp_path / "errors.sqlite3"
    first = record_incident(
        source="telegram",
        component="gateway",
        signature="provider timed out pid=100",
        error="Bearer very-secret-token",
        db_path=db,
    )
    duplicate = record_incident(
        source="telegram",
        component="gateway",
        signature="provider timed out pid=200",
        error="password=hunter2",
        db_path=db,
    )

    assert duplicate["fingerprint"] == first["fingerprint"]
    assert duplicate["occurrences"] == 2
    assert duplicate["last_error"] == "password=[REDACTED]"

    resolved = resolve_incident(
        fingerprint=first["fingerprint"],
        root_cause="stale provider connection",
        fix="recreate connection",
        verification="integration test passed",
        prevention="health check",
        artifacts=["https://user:secret@example.test/log"],
        db_path=db,
    )
    assert resolved["status"] == "resolved"
    assert resolved["artifacts"] == ["https://[REDACTED]@example.test/log"]

    regressed = record_incident(
        source="telegram",
        component="gateway",
        signature="provider timed out pid=300",
        db_path=db,
    )
    assert regressed["status"] == "regressed"
    assert regressed["occurrences"] == 3
    assert incident_stats(db_path=db) == {
        "schema_version": 1,
        "incidents": {"regressed": 1},
        "events": 4,
        "occurrences": 3,
        "db": str(db),
    }


def test_parallel_recording_is_serialized_without_lost_occurrences(tmp_path):
    db = tmp_path / "parallel.sqlite3"

    def observe(index: int):
        return record_incident(
            source="parallel-test",
            component="gateway",
            signature=f"delivery timeout pid={index}",
            db_path=db,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        incidents = list(pool.map(observe, range(16)))

    assert len({item["fingerprint"] for item in incidents}) == 1
    stored = list_incidents(db_path=db)
    assert len(stored) == 1
    assert stored[0]["occurrences"] == 16
    assert incident_stats(db_path=db)["events"] == 16


def test_resolution_requires_complete_learning_evidence(tmp_path):
    db = tmp_path / "errors.sqlite3"
    incident = record_incident(
        source="test", component="worker", signature="boom", db_path=db
    )
    with pytest.raises(ValueError, match="prevention"):
        resolve_incident(
            fingerprint=incident["fingerprint"],
            root_cause="bad state",
            fix="reset state",
            verification="test passed",
            prevention="",
            db_path=db,
        )


def test_search_list_export_and_secure_permissions(tmp_path):
    db = tmp_path / "private" / "errors.sqlite3"
    incident = record_incident(
        source="cron",
        component="backup",
        signature="snapshot upload failed",
        error="api_key=topsecret",
        context={"authorization": "Bearer abc.def.ghi"},
        db_path=db,
    )

    assert search_incidents("snapshot upload", db_path=db)[0]["fingerprint"] == incident["fingerprint"]
    assert list_incidents(status="open", db_path=db)[0]["last_error"] == "api_key=[REDACTED]"
    assert stat.S_IMODE(db.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(db.stat().st_mode) == 0o600

    output = tmp_path / "export" / "incidents.jsonl"
    result = export_jsonl(output, db_path=db)
    lines = output.read_text(encoding="utf-8").splitlines()
    assert result == {"output": str(output), "incidents": 1}
    assert len(lines) == 1
    exported = json.loads(lines[0])
    assert exported["fingerprint"] == incident["fingerprint"]
    assert "topsecret" not in lines[0]


def test_cli_round_trip_uses_supported_hermes_command(tmp_path):
    db = tmp_path / "cli.sqlite3"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])

    recorded = subprocess.run(
        [
            sys.executable,
            "-m",
            "hermes_cli.main",
            "errors",
            "--db",
            str(db),
            "record",
            "--source",
            "pytest",
            "--component",
            "cli",
            "--signature",
            "command failed",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    payload = json.loads(recorded.stdout)
    assert payload["status"] == "open"

    stats = subprocess.run(
        [sys.executable, "-m", "hermes_cli.main", "errors", "--db", str(db), "stats"],
        text=True,
        capture_output=True,
        env=env,
        check=True,
    )
    assert json.loads(stats.stdout)["incidents"] == {"open": 1}
