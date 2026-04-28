#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECK_ONLY=0
INSTALL_TSMUXER=1
USE_SUDO=1

usage() {
  cat <<'EOF'
Usage: ./scripts/install-bluray-deps.sh [options]

Installs/checks dependencies for the PowerPoint → Blu-ray autopilot workflow.

Options:
  --check-only       Report missing tools without installing packages
  --no-sudo          Do not use sudo; useful inside root containers
  --no-tsmuxer       Do not download/install local tsMuxer into tools/bin/
  -h, --help         Show this help

The script supports pacman, apt, dnf, zypper, and Homebrew where possible.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check-only) CHECK_ONLY=1 ;;
    --no-sudo) USE_SUDO=0 ;;
    --no-tsmuxer) INSTALL_TSMUXER=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
err() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }
have() { command -v "$1" >/dev/null 2>&1; }

run_priv() {
  if [[ $USE_SUDO -eq 1 && ${EUID:-$(id -u)} -ne 0 ]]; then
    sudo "$@"
  else
    "$@"
  fi
}

missing_tools=()
required_tools=(python3 ffmpeg ffprobe libreoffice pdftoppm curl unzip xorriso ant java)
for tool in "${required_tools[@]}"; do
  if ! have "$tool"; then
    missing_tools+=("$tool")
  fi
done

if [[ ${#missing_tools[@]} -eq 0 ]]; then
  say "All core command-line dependencies are already present."
else
  warn "Missing tools: ${missing_tools[*]}"
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
  if [[ $INSTALL_TSMUXER -eq 1 && ! -x "$ROOT/tools/bin/tsMuxer" && ! -x "$ROOT/tools/bin/tsMuxeR" && ! $(command -v tsMuxer 2>/dev/null || true) ]]; then
    warn "tsMuxer is not installed locally. Run ./scripts/get-tsmuxer.sh after dependencies are installed."
  fi
  exit 0
fi

if [[ ${#missing_tools[@]} -gt 0 ]]; then
  if have pacman; then
    say "Installing packages with pacman"
    # jdk8-openjdk keeps old HD Cook Book/BD-J builds happiest. jre/openjdk newer
    # may work for some pieces, but the sample build is historically Java 8-era.
    run_priv pacman -S --needed python ffmpeg libreoffice-fresh poppler curl unzip libisoburn apache-ant jdk8-openjdk
  elif have apt-get; then
    say "Installing packages with apt-get"
    run_priv apt-get update
    # openjdk-8-jdk is not available on many modern Ubuntu/Debian releases; the
    # build script can fall back to Docker/Podman if Java 8 is unavailable.
    run_priv apt-get install -y python3 ffmpeg libreoffice poppler-utils curl unzip xorriso ant default-jdk || {
      warn "apt package install failed. Try installing openjdk-8-jdk manually or use Docker/Podman fallback."
      exit 1
    }
  elif have dnf; then
    say "Installing packages with dnf"
    run_priv dnf install -y python3 ffmpeg libreoffice poppler-utils curl unzip xorriso ant java-1.8.0-openjdk-devel || \
      run_priv dnf install -y python3 ffmpeg libreoffice poppler-utils curl unzip xorriso ant java-latest-openjdk-devel
  elif have zypper; then
    say "Installing packages with zypper"
    run_priv zypper install -y python3 ffmpeg libreoffice poppler-tools curl unzip xorriso ant java-1_8_0-openjdk-devel || \
      run_priv zypper install -y python3 ffmpeg libreoffice poppler-tools curl unzip xorriso ant java-devel
  elif have brew; then
    say "Installing packages with Homebrew"
    brew install python ffmpeg libreoffice poppler curl unzip xorriso ant openjdk@8 || \
      brew install python ffmpeg libreoffice poppler curl unzip xorriso ant openjdk
  else
    err "No supported package manager found. Install these manually: ${required_tools[*]}"
    exit 1
  fi
fi

say "Ensuring tsMuxer is available"
if [[ $INSTALL_TSMUXER -eq 1 ]]; then
  "$ROOT/scripts/get-tsmuxer.sh"
else
  warn "Skipped tsMuxer download by request."
fi

say "Checking optional NVIDIA/NVENC support"
if have nvidia-smi; then
  python3 "$ROOT/tools/bluray_media_workflow.py" "/tmp" --gpu-status 2>/dev/null || true
else
  warn "nvidia-smi not found. GPU encode is optional; encoder=auto will fall back to CPU if NVENC is unavailable."
fi

say "Final tool check"
missing_after=()
for tool in "${required_tools[@]}"; do
  if ! have "$tool"; then
    missing_after+=("$tool")
  fi
done
if [[ ! -x "$ROOT/tools/bin/tsMuxer" && ! -x "$ROOT/tools/bin/tsMuxeR" && ! $(command -v tsMuxer 2>/dev/null || true) ]]; then
  missing_after+=(tsMuxer)
fi

if [[ ${#missing_after[@]} -gt 0 ]]; then
  err "Still missing: ${missing_after[*]}"
  exit 1
fi

say "Dependency installation complete."
cat <<EOF

Next:
  cd "$ROOT"
  ./scripts/monitor-bluray-project.sh "/home/corey/.openclaw/Bluray project"

EOF
