#!/usr/bin/env python3
"""Cross-platform dependency installer for Auto Blu-ray TUI."""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


APP_NAME = "Auto Blu-ray TUI"
WINDOWS_FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
WINDOWS_JAVA_URL = "https://learn.microsoft.com/java/openjdk/download"
HOMEBREW_INSTALL_URL = "https://brew.sh/"


class InstallerError(RuntimeError):
    """Raised for clean, user-facing installer failures."""


def root_dir() -> Path:
    return Path(__file__).resolve().parent


def requirements_path() -> Path:
    return root_dir() / "requirements.txt"


def venv_dir() -> Path:
    return root_dir() / ".venv"


def say(message: str) -> None:
    print(f"==> {message}")


def warn(message: str) -> None:
    print(f"WARN: {message}", file=sys.stderr)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run(cmd: Sequence[str], *, check: bool = True, dry_run: bool = False, cwd: Path | None = None) -> subprocess.CompletedProcess[str] | None:
    printable = " ".join(str(part) for part in cmd)
    if dry_run:
        print(f"DRY-RUN: {printable}")
        return None
    say(printable)
    try:
        return subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            check=check,
            text=True,
        )
    except FileNotFoundError as exc:
        raise InstallerError(f"Command not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise InstallerError(f"Command failed with exit code {exc.returncode}: {printable}") from exc


def sudo_prefix(use_sudo: bool) -> list[str]:
    if os.name == "nt" or not use_sudo:
        return []
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return []
    if command_exists("sudo"):
        return ["sudo"]
    raise InstallerError("Root privileges are required, but sudo was not found. Re-run as root or install sudo.")


def linux_distro_hint() -> str:
    os_release = Path("/etc/os-release")
    if not os_release.exists():
        return ""
    try:
        text = os_release.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return ""
    if "arch" in text or "manjaro" in text:
        return "arch"
    if "debian" in text or "ubuntu" in text or "mint" in text or "pop" in text:
        return "debian"
    return ""


def install_linux(*, dry_run: bool, check_only: bool, use_sudo: bool) -> None:
    missing = [tool for tool in ("ffmpeg", "java") if not command_exists(tool)]
    if not missing:
        say("Linux system dependencies already appear to be installed.")
        return
    warn(f"Missing system tools: {', '.join(missing)}")
    if check_only:
        return

    prefix = sudo_prefix(use_sudo)
    distro = linux_distro_hint()

    if command_exists("pacman") or distro == "arch":
        # jdk8-openjdk keeps old BD-J tooling happiest; it satisfies Java 8+.
        run(prefix + ["pacman", "-S", "--needed", "ffmpeg", "jdk8-openjdk"], dry_run=dry_run)
        return

    if command_exists("apt-get") or distro == "debian":
        run(prefix + ["apt-get", "update"], dry_run=dry_run)
        run(prefix + ["apt-get", "install", "-y", "ffmpeg", "default-jdk"], dry_run=dry_run)
        return

    raise InstallerError(
        "Unsupported Linux package manager. Install ffmpeg and OpenJDK 8+ manually, "
        "or add support for your distro package manager in install.py."
    )


def install_macos(*, dry_run: bool, check_only: bool) -> None:
    missing = [tool for tool in ("ffmpeg", "java", "xorriso", "pdftoppm") if not command_exists(tool)]
    if not command_exists("libreoffice") and not command_exists("soffice"):
        missing.append("libreoffice")
    if not missing:
        say("macOS system dependencies already appear to be installed.")
        warn("Packaged macOS release archives already include a bundled tsMuxer. Source checkouts still need their own compatible tsMuxer if final authoring fails.")
        return
    warn(f"Missing system tools: {', '.join(missing)}")
    if check_only:
        warn("Packaged macOS release archives already include a bundled tsMuxer. Source checkouts still need a compatible tsMuxer on PATH or in tools/bin.")
        return

    if not command_exists("brew"):
        raise InstallerError(
            "Homebrew is not installed. Install it from:\n"
            f"  {HOMEBREW_INSTALL_URL}\n"
            "Then re-run: python3 install.py"
        )

    run(["brew", "install", "ffmpeg", "xorriso", "poppler"], dry_run=dry_run)
    run(["brew", "install", "--cask", "libreoffice"], dry_run=dry_run)
    run(["brew", "install", "--cask", "temurin@17"], dry_run=dry_run)
    warn("If java is still not found after Homebrew finishes, run /usr/libexec/java_home -V and make sure PATH/JAVA_HOME expose the installed JDK.")
    warn("Packaged macOS release archives already include a bundled tsMuxer. Source checkouts should download/build a compatible tsMuxer and place it in tools/bin or on PATH.")


def install_windows(*, dry_run: bool, check_only: bool) -> None:
    missing = [tool for tool in ("ffmpeg", "java") if not command_exists(tool)]
    if not missing:
        say("Windows system dependencies already appear to be installed.")
        return
    warn(f"Missing system tools: {', '.join(missing)}")
    if check_only:
        return

    if command_exists("winget"):
        # --accept flags keep the command non-interactive on current winget.
        run([
            "winget", "install", "--id", "Gyan.FFmpeg", "--exact",
            "--accept-package-agreements", "--accept-source-agreements",
        ], dry_run=dry_run)
        run([
            "winget", "install", "--id", "Microsoft.OpenJDK.11", "--exact",
            "--accept-package-agreements", "--accept-source-agreements",
        ], dry_run=dry_run)
        return

    if command_exists("scoop"):
        run(["scoop", "install", "ffmpeg", "openjdk"], dry_run=dry_run)
        return

    raise InstallerError(
        "No supported Windows package manager found. Install one of these, then re-run install.py:\n"
        "  winget: usually included with Windows App Installer\n"
        "  scoop: https://scoop.sh/\n\n"
        "Manual install URLs:\n"
        f"  ffmpeg: {WINDOWS_FFMPEG_URL}\n"
        f"  Java/OpenJDK: {WINDOWS_JAVA_URL}\n"
        "After installing, make sure both ffmpeg.exe and java.exe are available in PATH."
    )


def venv_python(path: Path) -> Path:
    if platform.system() == "Windows":
        return path / "Scripts" / "python.exe"
    return path / "bin" / "python"


def ensure_venv(*, python_exe: str, dry_run: bool, recreate: bool) -> Path:
    path = venv_dir()
    py = venv_python(path)

    if recreate and path.exists():
        if dry_run:
            print(f"DRY-RUN: remove {path}")
        else:
            shutil.rmtree(path)

    if not py.exists():
        run([python_exe, "-m", "venv", str(path)], dry_run=dry_run)
    else:
        say(f"Using existing virtual environment: {path}")

    return py


def install_python_requirements(*, python_exe: str, dry_run: bool, recreate_venv: bool, check_only: bool) -> None:
    req = requirements_path()
    if not req.is_file():
        raise InstallerError(f"Missing requirements.txt: {req}")
    if check_only:
        say(f"Would install Python requirements from {req} into {venv_dir()}")
        return

    py = ensure_venv(python_exe=python_exe, dry_run=dry_run, recreate=recreate_venv)
    run([str(py), "-m", "pip", "install", "--upgrade", "pip"], dry_run=dry_run)
    run([str(py), "-m", "pip", "install", "-r", str(req)], dry_run=dry_run)


def install_system_dependencies(system_name: str, *, dry_run: bool, check_only: bool, use_sudo: bool, skip_system: bool) -> None:
    if skip_system:
        say("Skipping system package installation.")
        return

    if system_name == "Linux":
        install_linux(dry_run=dry_run, check_only=check_only, use_sudo=use_sudo)
    elif system_name == "Darwin":
        install_macos(dry_run=dry_run, check_only=check_only)
    elif system_name == "Windows":
        install_windows(dry_run=dry_run, check_only=check_only)
    else:
        raise InstallerError(f"Unsupported OS: {system_name}. Install ffmpeg and OpenJDK 8+ manually.")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Install dependencies for {APP_NAME}.")
    parser.add_argument("--check-only", action="store_true", help="Report what would be checked/installed without installing.")
    parser.add_argument("--dry-run", action="store_true", help="Print install commands without running them.")
    parser.add_argument("--no-system", action="store_true", help="Skip ffmpeg/java package-manager installation.")
    parser.add_argument("--no-venv", action="store_true", help="Skip .venv creation and Python requirements installation.")
    parser.add_argument("--recreate-venv", action="store_true", help="Delete and recreate .venv before installing requirements.")
    parser.add_argument("--no-sudo", action="store_true", help="Do not use sudo for Linux package installs.")
    parser.add_argument("--python", default=sys.executable, help="Python executable to use for venv reporting; defaults to this Python.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    system_name = platform.system()

    try:
        say(f"{APP_NAME} installer")
        say(f"OS: {system_name} ({platform.platform()})")
        say(f"Project root: {root_dir()}")

        install_system_dependencies(
            system_name,
            dry_run=args.dry_run,
            check_only=args.check_only,
            use_sudo=not args.no_sudo,
            skip_system=args.no_system,
        )

        if args.no_venv:
            say("Skipping Python virtual environment setup.")
        else:
            install_python_requirements(
                python_exe=args.python,
                dry_run=args.dry_run,
                recreate_venv=args.recreate_venv,
                check_only=args.check_only,
            )

        say("Dependency setup complete.")
        say("Next: python start.py \"/path/to/project\"")
        return 0
    except InstallerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
