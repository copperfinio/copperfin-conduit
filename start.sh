#!/usr/bin/env bash
# Compatibility launcher for Conduit.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${1:-20129}"
shift || true

exec python3 -m conduit.cli start --background --port "$PORT" "$@"
