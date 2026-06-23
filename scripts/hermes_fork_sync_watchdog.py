#!/usr/bin/env python3
"""Quiet watchdog for Hermes fork/upstream drift.

The script is intentionally non-mutating with respect to the working tree: it may
refresh remote-tracking refs when --fetch is used, but it never pulls, rebases,
checks out, restarts services, or edits files. It prints nothing on a healthy
cron tick unless --dry-run is set.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run_git(repo: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def count_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def parse_count(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        raise SystemExit(f"invalid integer override: {value!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("HERMES_FORK_WATCH_REPO", str(Path.home() / ".hermes" / "hermes-agent")))
    parser.add_argument("--remote", default=os.environ.get("HERMES_FORK_WATCH_REMOTE", "origin"))
    parser.add_argument("--upstream-branch", default=os.environ.get("HERMES_FORK_WATCH_UPSTREAM_BRANCH", "main"))
    parser.add_argument("--behind-threshold", type=int, default=int(os.environ.get("HERMES_FORK_WATCH_BEHIND_THRESHOLD", "25")))
    parser.add_argument("--dirty-alert", action=argparse.BooleanOptionalAction, default=os.environ.get("HERMES_FORK_WATCH_DIRTY_ALERT", "1") != "0")
    parser.add_argument("--fetch", action=argparse.BooleanOptionalAction, default=os.environ.get("HERMES_FORK_WATCH_FETCH", "1") != "0")
    parser.add_argument("--dry-run", action="store_true", help="Always print the observed state.")
    parser.add_argument("--mock-behind", type=int, default=parse_count(os.environ.get("HERMES_FORK_WATCH_MOCK_BEHIND")))
    parser.add_argument("--mock-dirty", type=int, default=parse_count(os.environ.get("HERMES_FORK_WATCH_MOCK_DIRTY")))
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not (repo / ".git").exists():
        print(f"Hermes fork watchdog: repo is not a git checkout: {repo}")
        return 2

    upstream_ref = f"{args.remote}/{args.upstream_branch}"
    fetch_error = ""
    if args.fetch and args.mock_behind is None:
        fetched = run_git(repo, ["fetch", "--quiet", args.remote, args.upstream_branch], check=False)
        if fetched.returncode != 0:
            fetch_error = (fetched.stderr or fetched.stdout).strip()

    branch = run_git(repo, ["branch", "--show-current"]).stdout.strip() or "(detached)"
    head = run_git(repo, ["rev-parse", "--short", "HEAD"]).stdout.strip()

    if args.mock_behind is not None:
        behind = args.mock_behind
        ahead = 0
    else:
        rev = run_git(repo, ["rev-list", "--left-right", "--count", f"HEAD...{upstream_ref}"], check=False)
        if rev.returncode != 0:
            print(f"Hermes fork watchdog: cannot compare HEAD with {upstream_ref}: {(rev.stderr or rev.stdout).strip()}")
            return 2
        ahead_s, behind_s = rev.stdout.strip().split()
        ahead, behind = int(ahead_s), int(behind_s)

    dirty = args.mock_dirty if args.mock_dirty is not None else count_lines(run_git(repo, ["status", "--short"]).stdout)

    alerts: list[str] = []
    if fetch_error:
        alerts.append(f"fetch_error={fetch_error}")
    if behind >= args.behind_threshold:
        alerts.append(f"behind={behind} threshold={args.behind_threshold}")
    if args.dirty_alert and dirty > 0:
        alerts.append(f"dirty_files={dirty}")

    summary = (
        f"Hermes fork watchdog: repo={repo} branch={branch} head={head} "
        f"upstream={upstream_ref} ahead={ahead} behind={behind} dirty={dirty}"
    )
    if alerts:
        print(summary)
        print("alerts: " + "; ".join(alerts))
        print("no mutation performed: no pull, rebase, checkout, restart, or file edit was attempted")
        # Script-only Hermes cron treats non-zero exit as a broken watchdog.
        # Alert conditions are normal output and must exit cleanly.
        return 0
    if args.dry_run:
        print(summary)
        print("silent_green=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
