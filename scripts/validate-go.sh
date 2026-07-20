#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

"$REPO_ROOT/go" doctor "$REPO_ROOT" --json
"$REPO_ROOT/go" validate "$REPO_ROOT"
"$REPO_ROOT/go" status "$REPO_ROOT" --json
"$REPO_ROOT/go" readback "$REPO_ROOT"