#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f user.vars.properties ]]; then
  cp user.vars.properties.example user.vars.properties
fi

java_major() {
  java -version 2>&1 | awk -F '[".]' '/version/ {
    if ($2 == "1") print $3;
    else print $2;
    exit
  }'
}

if command -v java >/dev/null 2>&1 && command -v ant >/dev/null 2>&1; then
  major="$(java_major || true)"

  if [[ "$major" == "8" ]]; then
    echo "Using local Java 8 for HD Cookbook BD-J build:"
    java -version
    ant spotless hdcookbook-discimage
    exit 0
  fi

  cat >&2 <<ERR
Local Java is not Java 8; detected Java major version: ${major:-unknown}.

HD Cookbook's legacy BD-J build/signing tools must run under Java 8.
Using newer Java can produce a Blu-ray menu JAR that VLC/libbluray rejects with:
  java.lang.SecurityException: cannot verify signature block file META-INF/SIG-BD00

Trying the JDK 8 container fallback...
ERR
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  docker build -f Dockerfile.jdk8 -t hdcookbook-jdk8 .
  docker run --rm \
    -u "$(id -u):$(id -g)" \
    -v "$ROOT:/work/hdcookbook" \
    hdcookbook-jdk8 \
    ant spotless hdcookbook-discimage
  exit 0
fi

if command -v podman >/dev/null 2>&1; then
  podman build -f Dockerfile.jdk8 -t hdcookbook-jdk8 .
  podman run --rm \
    -u "$(id -u):$(id -g)" \
    -v "$ROOT:/work/hdcookbook:Z" \
    hdcookbook-jdk8 \
    ant spotless hdcookbook-discimage
  exit 0
fi

cat >&2 <<'ERR'
Need one of:
  - local JDK 8 + Apache Ant
  - a running Docker daemon
  - Podman

On Arch/Manjaro, local packages are typically:
  sudo pacman -S jdk8-openjdk ant
  sudo archlinux-java set java-8-openjdk

If Docker is installed but inactive, start it first, then rerun this script.
ERR
exit 1
