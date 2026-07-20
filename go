#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACK="$(GO_STACK="${GO_STACK:-}" bash "$REPO_ROOT/scripts/bootstrap-go-workflow-stack.sh")"

if [ -z "$STACK" ] || [ ! -f "$STACK/cli/go.py" ]; then
  echo "go-workflow-stack not found; set GO_STACK to an exact pinned checkout" >&2
  exit 2
fi

export GO_STACK="$STACK"
exec python3 "$STACK/cli/go.py" "$@"