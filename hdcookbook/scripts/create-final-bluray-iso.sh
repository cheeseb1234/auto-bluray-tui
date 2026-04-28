#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="${1:-/home/corey/.openclaw/Bluray project}"
shift || true
python3 "$ROOT/tools/final_bluray_iso.py" "$PROJECT_DIR" "$@"
