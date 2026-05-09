#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/Blu-ray project" >&2
  exit 2
fi
PROJECT_DIR="$1"
"$ROOT/scripts/convert-pptx-menu.sh" "$PROJECT_DIR" >/dev/null
cd "$ROOT/xlets/grin_samples/Scripts/PptxMenu"
exec ant preview
