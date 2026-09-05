"""Profile-scoped, persistent incident and fix knowledge for Hermes Agent.

The canonical store lives below the active ``HERMES_HOME`` so profiles never
share incident state accidentally.  This module is dependency-free and safe to
use from the CLI, plugins, cron jobs, and agent workflows.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from hermes_constants import get_hermes_home

SCHEMA_VERSION = 1

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(token|api[_-]?key|password|passwd|secret|authorization)\b\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@"),
)


def default_db_path() -> Path:
    """Return the canonical incident database for the active Hermes profile."""
    return get_hermes_home() / "state" / "error-knowledge" / "errors.sqlite3"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(value: Any) -> Any:
    """Recursively redact common credential shapes before persistence."""
    if isinstance(value, dict):
        return {str(key): redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    text = value
    text = _SECRET_PATTERNS[0].sub("Bearer [REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _SECRET_PATTERNS[2].sub("[REDACTED_BOT_TOKEN]", text)
    text = _SECRET_PATTERNS[3].sub(r"\1[REDACTED]@", text)
    return text


def normalize(text: str) -> str:
    value = str(redact(text)).strip().lower()
    value = re.sub(r"\b\d{4}-\d{2}-\d{2}[t ][0-9:.+z-]+\b", "<timestamp>", value)
    value = re.sub(r"\bpid[=: ]+\d+\b", "pid=<n>", value)
    value = re.sub(r"\s+", " ", value)
    return value[:1000]


def incident_fingerprint(component: str, signature: str) -> str:
    canonical = f"{normalize(component)}\n{normalize(signature)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _db_path(path: str | Path | None) -> Path:
    return Path(path).expanduser() if path is not None else default_db_path()


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open and initialize the canonical schema without forking old databases."""
    db_path = _db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        db_path.parent.chmod(0o700)
    except OSError:
        pass
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS incidents (
            fingerprint TEXT PRIMARY KEY,
            component TEXT NOT NULL,
            signature TEXT NOT NULL,
            category TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('open','resolved','regressed')),
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            resolved_at TEXT,
            occurrences INTEGER NOT NULL DEFAULT 1,
            last_error TEXT NOT NULL,
            context_json TEXT NOT NULL DEFAULT '{}',
            root_cause TEXT,
            fix_summary TEXT,
            prevention TEXT,
            verification TEXT,
            artifacts_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL REFERENCES incidents(fingerprint),
            event_type TEXT NOT NULL CHECK(event_type IN ('observed','resolved','regressed','note')),
            occurred_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_incidents_status_last_seen
            ON incidents(status, last_seen DESC);
        CREATE INDEX IF NOT EXISTS idx_events_fingerprint_id
            ON events(fingerprint, id);
        """
    )
    conn.execute(
        "INSERT INTO metadata(key,value) VALUES('schema_version',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    try:
        os.chmod(db_path, 0o600)
    except OSError:
        pass
    return conn


def _context(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("context must be a JSON object")
    return redact(value)


def _decode_rows(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("context_json", "artifacts_json", "payload_json"):
            if key not in item:
                continue
            try:
                item[key.removesuffix("_json")] = json.loads(item.pop(key))
            except json.JSONDecodeError:
                pass
        result.append(item)
    return result


def record_incident(
    *,
    source: str,
    component: str,
    signature: str,
    error: str | None = None,
    category: str = "runtime",
    context: dict[str, Any] | None = None,
    occurred_at: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    when = occurred_at or now_iso()
    safe_component = str(redact(component)).strip()
    safe_signature = str(redact(signature)).strip()
    safe_error = str(redact(error or signature)).strip()
    safe_source = str(redact(source)).strip()
    safe_category = str(redact(category)).strip()
    safe_context = _context(context)
    if not safe_component or not safe_signature or not safe_source or not safe_category:
        raise ValueError("source, component, signature, and category must be non-empty")
    fingerprint = incident_fingerprint(safe_component, safe_signature)
    with connect(db_path) as conn:
        # Serialize the short read-then-upsert sequence across concurrent agents.
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT status, occurrences FROM incidents WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        event_type = "regressed" if existing and existing["status"] == "resolved" else "observed"
        if existing:
            next_status = "regressed" if event_type == "regressed" else existing["status"]
            conn.execute(
                """UPDATE incidents SET category=?, source=?, status=?, last_seen=?,
                   occurrences=occurrences+1, last_error=?, context_json=? WHERE fingerprint=?""",
                (
                    safe_category,
                    safe_source,
                    next_status,
                    when,
                    safe_error,
                    json.dumps(safe_context, ensure_ascii=False, sort_keys=True),
                    fingerprint,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO incidents(
                   fingerprint, component, signature, category, source, status,
                   first_seen, last_seen, last_error, context_json
                   ) VALUES(?,?,?,?,?,'open',?,?,?,?)""",
                (
                    fingerprint,
                    safe_component,
                    safe_signature,
                    safe_category,
                    safe_source,
                    when,
                    when,
                    safe_error,
                    json.dumps(safe_context, ensure_ascii=False, sort_keys=True),
                ),
            )
        payload = {
            "error": safe_error,
            "context": safe_context,
            "source": safe_source,
            "category": safe_category,
        }
        conn.execute(
            "INSERT INTO events(fingerprint,event_type,occurred_at,payload_json) VALUES(?,?,?,?)",
            (fingerprint, event_type, when, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM incidents WHERE fingerprint=?", (fingerprint,)).fetchone()
    return _decode_rows([row])[0]


def resolve_incident(
    *,
    fingerprint: str,
    root_cause: str,
    fix: str,
    verification: str,
    prevention: str,
    artifacts: Iterable[str] = (),
    resolved_at: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    required = {
        "root-cause": root_cause,
        "fix": fix,
        "verification": verification,
        "prevention": prevention,
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    if missing:
        raise ValueError("resolve requires non-empty " + ", ".join(missing))
    when = resolved_at or now_iso()
    safe_artifacts = [str(redact(item)) for item in artifacts]
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT fingerprint FROM incidents WHERE fingerprint=?", (fingerprint,)).fetchone()
        if not row:
            raise ValueError(f"unknown fingerprint: {fingerprint}")
        safe_root_cause = str(redact(root_cause))
        safe_fix = str(redact(fix))
        safe_verification = str(redact(verification))
        safe_prevention = str(redact(prevention))
        conn.execute(
            """UPDATE incidents SET status='resolved', resolved_at=?, root_cause=?, fix_summary=?,
               prevention=?, verification=?, artifacts_json=? WHERE fingerprint=?""",
            (
                when,
                safe_root_cause,
                safe_fix,
                safe_prevention,
                safe_verification,
                json.dumps(safe_artifacts, ensure_ascii=False),
                fingerprint,
            ),
        )
        payload = {
            "root_cause": safe_root_cause,
            "fix": safe_fix,
            "prevention": safe_prevention,
            "verification": safe_verification,
            "artifacts": safe_artifacts,
        }
        conn.execute(
            "INSERT INTO events(fingerprint,event_type,occurred_at,payload_json) VALUES(?,?,?,?)",
            (fingerprint, "resolved", when, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )
        conn.commit()
        result = conn.execute("SELECT * FROM incidents WHERE fingerprint=?", (fingerprint,)).fetchone()
    return _decode_rows([result])[0]


def list_incidents(
    *, status: str | None = None, limit: int = 50, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    if status not in {None, "open", "resolved", "regressed"}:
        raise ValueError(f"unsupported status: {status}")
    query = "SELECT * FROM incidents"
    params: list[Any] = []
    if status:
        query += " WHERE status=?"
        params.append(status)
    query += " ORDER BY last_seen DESC LIMIT ?"
    params.append(max(1, limit))
    with connect(db_path) as conn:
        return _decode_rows(conn.execute(query, params).fetchall())


def search_incidents(
    query: str, *, limit: int = 20, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    terms = [term for term in normalize(query).split(" ") if term]
    if not terms:
        return []
    clauses: list[str] = []
    params: list[Any] = []
    for term in terms:
        clauses.append(
            "lower(component || ' ' || signature || ' ' || last_error || ' ' || "
            "coalesce(root_cause,'') || ' ' || coalesce(fix_summary,'') || ' ' || "
            "coalesce(prevention,'')) LIKE ?"
        )
        params.append(f"%{term}%")
    params.append(max(1, limit))
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM incidents WHERE {' AND '.join(clauses)} "
            "ORDER BY last_seen DESC LIMIT ?",
            params,
        ).fetchall()
    return _decode_rows(rows)


def incident_stats(*, db_path: str | Path | None = None) -> dict[str, Any]:
    resolved_path = _db_path(db_path)
    with connect(resolved_path) as conn:
        counts = {
            row["status"]: row["n"]
            for row in conn.execute("SELECT status, count(*) n FROM incidents GROUP BY status")
        }
        total_events = conn.execute("SELECT count(*) FROM events").fetchone()[0]
        total_occurrences = conn.execute("SELECT coalesce(sum(occurrences),0) FROM incidents").fetchone()[0]
    return {
        "schema_version": SCHEMA_VERSION,
        "incidents": counts,
        "events": total_events,
        "occurrences": total_occurrences,
        "db": str(resolved_path),
    }


def export_jsonl(output: str | Path, *, db_path: str | Path | None = None) -> dict[str, Any]:
    output_path = Path(output).expanduser()
    with connect(db_path) as conn:
        incidents = _decode_rows(
            conn.execute("SELECT * FROM incidents ORDER BY first_seen, fingerprint").fetchall()
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=output_path.name + ".", dir=output_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for item in incidents:
                handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"output": str(output_path), "incidents": len(incidents)}


def ingest_failure_map(
    failures: dict[str, str],
    *,
    source: str,
    category: str = "automation",
    context: dict[str, Any] | None = None,
    occurred_at: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    if not isinstance(failures, dict):
        raise ValueError("ingest input must be a JSON object of component -> error")
    recorded: list[str] = []
    for component, error in sorted(failures.items()):
        if not isinstance(error, str):
            raise ValueError(f"ingest error for {component!r} must be a string")
        item = record_incident(
            source=source,
            component=str(component),
            signature=error,
            error=error,
            category=category,
            context=context,
            occurred_at=occurred_at,
            db_path=db_path,
        )
        recorded.append(item["fingerprint"])
    return {"recorded": recorded, "count": len(recorded)}
