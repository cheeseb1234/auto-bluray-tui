#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="${1:-/home/corey/.openclaw/Bluray project}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ISO="$PROJECT_DIR/build/final-bluray/bluray-project.iso"
PYTHON_BIN="${AUTO_BLURAY_PYTHON:-python3}"
"$PYTHON_BIN" "$ROOT/tools/bluray_burn.py" "$ISO" --auto
