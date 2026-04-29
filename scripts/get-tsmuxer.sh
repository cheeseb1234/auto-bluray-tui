#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${TSMUXER_VERSION:-2.7.0}"
BASE="https://github.com/justdan96/tsMuxer/releases/download/${VERSION}"
ZIP="tsMuxer-${VERSION}-linux.zip"
DL="$ROOT/tools/downloads"
BIN="$ROOT/tools/bin"
mkdir -p "$DL" "$BIN"
cd "$DL"
if [[ ! -f "$ZIP" ]]; then
  curl -L -o "$ZIP" "$BASE/$ZIP"
fi
rm -rf "tsMuxer-${VERSION}-linux"
mkdir "tsMuxer-${VERSION}-linux"
unzip -q "$ZIP" -d "tsMuxer-${VERSION}-linux"
cp "tsMuxer-${VERSION}-linux/tsMuxeR" "$BIN/tsMuxer"
chmod +x "$BIN/tsMuxer"
"$BIN/tsMuxer" 2>&1 | head -5
