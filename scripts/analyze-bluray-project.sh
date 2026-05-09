#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/Blu-ray project" >&2
  exit 2
fi
PROJECT_DIR="$1"
PYTHON_BIN="${AUTO_BLURAY_PYTHON:-python3}"
"$PYTHON_BIN" "$ROOT/tools/bluray_media_workflow.py" "$PROJECT_DIR" --write-manifest --plan
