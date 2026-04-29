#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="${1:-/home/corey/.openclaw/Bluray project}"
"$ROOT/scripts/convert-pptx-menu.sh" "$PROJECT_DIR" >/dev/null
cd "$ROOT/xlets/grin_samples/Scripts/PptxMenu"
exec ant preview
