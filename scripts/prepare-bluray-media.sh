#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="${1:-/home/corey/.openclaw/Bluray project}"
shift || true
PYTHON_BIN="${AUTO_BLURAY_PYTHON:-python3}"
"$PYTHON_BIN" "$ROOT/tools/bluray_media_workflow.py" "$PROJECT_DIR" --write-manifest --plan --encode "$@"
