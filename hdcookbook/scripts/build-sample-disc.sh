#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f user.vars.properties ]]; then
  cp user.vars.properties.example user.vars.properties
fi

if command -v java >/dev/null 2>&1 && command -v ant >/dev/null 2>&1; then
  ant hdcookbook-discimage
  exit 0
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker build -f Dockerfile.jdk8 -t hdcookbook-jdk8 .
  docker run --rm -u "$(id -u):$(id -g)" -v "$ROOT:/work/hdcookbook" hdcookbook-jdk8 ant hdcookbook-discimage
  exit 0
fi

if command -v podman >/dev/null 2>&1; then
  podman build -f Dockerfile.jdk8 -t hdcookbook-jdk8 .
  podman run --rm -u "$(id -u):$(id -g)" -v "$ROOT:/work/hdcookbook:Z" hdcookbook-jdk8 ant hdcookbook-discimage
  exit 0
fi

cat >&2 <<'ERR'
Need one of:
  - local JDK 8 + Apache Ant
  - a running Docker daemon
  - Podman

On Arch/Manjaro, local packages are typically:
  sudo pacman -S jdk8-openjdk ant

If Docker is installed but inactive, start it first, then rerun this script.
ERR
exit 1
