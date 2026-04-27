#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAMPLE="$ROOT/xlets/hdcookbook_discimage"
STUBS="$ROOT/lib/stubs/enhanced/classes.zip"

cd "$SAMPLE"
exec ant -DHDC_BDJ_PLATFORM_CLASSES="$STUBS" -f run_jdktools.xml run-grinview-menu
