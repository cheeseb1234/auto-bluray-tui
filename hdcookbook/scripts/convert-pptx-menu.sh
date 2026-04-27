#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="${1:-/home/corey/.openclaw/Bluray project}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/xlets/grin_samples/Scripts/PptxMenu"
python3 "$ROOT/tools/pptx_menu_converter.py" "$PROJECT_DIR" "$OUT"
