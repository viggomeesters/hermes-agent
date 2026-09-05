"""Implementation and parser for ``hermes errors``."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from hermes_cli.error_knowledge import (
    export_jsonl,
    incident_stats,
    ingest_failure_map,
    list_incidents,
    record_incident,
    resolve_incident,
    search_incidents,
)


def _parse_context(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("context-json must be a JSON object")
    return value


def _print_result(value: Any, *, text: bool = False) -> None:
    if not text:
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if isinstance(value, list):
        for item in value:
            print(f"{item['fingerprint']} {item['status']:9} {item['component']} — {item['signature']}")
        return
    print(value)


def run_errors(args: argparse.Namespace) -> None:
    """Execute one supported incident knowledge operation."""
    db_path = getattr(args, "db", None)
    command = args.errors_command
    try:
        if command == "init":
            result = incident_stats(db_path=db_path)
        elif command == "record":
            result = record_incident(
                source=args.source,
                component=args.component,
                signature=args.signature,
                error=args.error,
                category=args.category,
                context=_parse_context(args.context_json),
                occurred_at=args.occurred_at,
                db_path=db_path,
            )
        elif command == "resolve":
            result = resolve_incident(
                fingerprint=args.fingerprint,
                root_cause=args.root_cause,
                fix=args.fix,
                verification=args.verification,
                prevention=args.prevention,
                artifacts=args.artifact or (),
                resolved_at=args.resolved_at,
                db_path=db_path,
            )
        elif command == "ingest":
            if args.input == "-":
                import sys

                raw = sys.stdin.read()
            else:
                raw = Path(args.input).read_text(encoding="utf-8")
            failures = json.loads(raw)
            result = ingest_failure_map(
                failures,
                source=args.source,
                category=args.category,
                context=_parse_context(args.context_json),
                occurred_at=args.occurred_at,
                db_path=db_path,
            )
        elif command == "list":
            result = list_incidents(status=args.status, limit=args.limit, db_path=db_path)
        elif command == "search":
            result = search_incidents(args.query, limit=args.limit, db_path=db_path)
        elif command == "stats":
            result = incident_stats(db_path=db_path)
        elif command == "export":
            result = export_jsonl(args.output, db_path=db_path)
        else:  # pragma: no cover - argparse enforces a subcommand
            raise ValueError(f"unsupported errors command: {command}")
    except (ValueError, json.JSONDecodeError, OSError, sqlite3.Error) as exc:
        raise SystemExit(f"error: {exc}") from exc
    _print_result(result, text=getattr(args, "text", False))


def build_errors_parser(subparsers, *, cmd_errors=run_errors) -> None:
    parser = subparsers.add_parser(
        "errors",
        help="Persistent incident and verified-fix knowledge",
        description=(
            "Search, record, resolve, and export the profile-scoped Hermes incident database. "
            "The canonical store lives under the active HERMES_HOME."
        ),
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Override the database path (primarily for tests and recovery)",
    )
    commands = parser.add_subparsers(dest="errors_command", required=True)

    command = commands.add_parser("init", help="Initialize the database and show statistics")
    command.set_defaults(func=cmd_errors)

    command = commands.add_parser("record", help="Record or increment an observed incident")
    command.add_argument("--source", required=True)
    command.add_argument("--component", required=True)
    command.add_argument("--signature", required=True)
    command.add_argument("--error")
    command.add_argument("--category", default="runtime")
    command.add_argument("--context-json")
    command.add_argument("--occurred-at")
    command.set_defaults(func=cmd_errors)

    command = commands.add_parser("resolve", help="Resolve an incident with complete learning evidence")
    command.add_argument("--fingerprint", required=True)
    command.add_argument("--root-cause", required=True)
    command.add_argument("--fix", required=True)
    command.add_argument("--verification", required=True)
    command.add_argument("--prevention", required=True)
    command.add_argument("--artifact", action="append")
    command.add_argument("--resolved-at")
    command.set_defaults(func=cmd_errors)

    command = commands.add_parser("ingest", help="Record a JSON object of component-to-error entries")
    command.add_argument("--source", required=True)
    command.add_argument("--category", default="automation")
    command.add_argument("--input", default="-", help="JSON object file, or - for stdin")
    command.add_argument("--context-json")
    command.add_argument("--occurred-at")
    command.set_defaults(func=cmd_errors)

    command = commands.add_parser("list", help="List recent incidents")
    command.add_argument("--status", choices=("open", "resolved", "regressed"))
    command.add_argument("--limit", type=int, default=50)
    command.add_argument("--text", action="store_true")
    command.set_defaults(func=cmd_errors)

    command = commands.add_parser("search", help="Search reusable incident and fix knowledge")
    command.add_argument("query")
    command.add_argument("--limit", type=int, default=20)
    command.add_argument("--text", action="store_true")
    command.set_defaults(func=cmd_errors)

    command = commands.add_parser("stats", help="Show incident, event, and occurrence counts")
    command.set_defaults(func=cmd_errors)

    command = commands.add_parser("export", help="Write a portable read-only JSONL export")
    command.add_argument("--output", type=Path, required=True)
    command.set_defaults(func=cmd_errors)
