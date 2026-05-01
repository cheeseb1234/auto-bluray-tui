#!/usr/bin/env python3
"""Cross-platform launcher for Auto Blu-ray TUI.

This replaces scripts/monitor-bluray-project.sh as the project entry point.
It intentionally avoids shell-specific behavior so it can run on Windows,
macOS, and Linux.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence


APP_NAME = "Auto Blu-ray TUI"
MIN_PYTHON = (3, 10)
REQUIRED_TOOLS = ("java", "ffmpeg")
OPTIONAL_TOOLS = ("ffprobe",)


class LauncherError(RuntimeError):
    """Raised for clean, user-facing launcher failures."""


def project_root() -> Path:
    return Path(__file__).resolve().parent


def tools_dir() -> Path:
    return project_root() / "tools"


def tui_script() -> Path:
    return tools_dir() / "bluray_tui_monitor.py"


def normalize_project_dir(raw: str) -> Path:
    # expanduser is useful on Unix/macOS and harmless on Windows.
    return Path(raw).expanduser().resolve()


def stream_command(cmd: Sequence[str], *, cwd: Path | None = None) -> int:
    """Run a command with inherited stdio so curses/TUI rendering is preserved."""
    try:
        completed = subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            stdin=None,
            stdout=None,
            stderr=None,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LauncherError(f"Command not found: {cmd[0]}") from exc
    except OSError as exc:
        raise LauncherError(f"Failed to launch {cmd[0]!r}: {exc}") from exc
    return int(completed.returncode)


def capture_command(cmd: Sequence[str], *, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    """Run a short probe command and capture output for diagnostics."""
    try:
        return subprocess.run(
            list(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise LauncherError(f"Command not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise LauncherError(f"Timed out while checking {cmd[0]!r}") from exc
    except OSError as exc:
        raise LauncherError(f"Failed to run {cmd[0]!r}: {exc}") from exc


def first_output_line(result: subprocess.CompletedProcess[str]) -> str:
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line:
            return line
    return "no version output"


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        wanted = ".".join(str(part) for part in MIN_PYTHON)
        found = platform.python_version()
        raise LauncherError(f"Python {wanted}+ is required; found Python {found} at {sys.executable}")


def which_required(name: str) -> Path:
    found = shutil.which(name)
    if not found:
        system = platform.system()
        install_hint = {
            "Windows": "Install it and make sure its bin folder is added to PATH.",
            "Darwin": "Install it with Homebrew or another package manager, then make sure it is on PATH.",
            "Linux": "Install it with your distro package manager, then make sure it is on PATH.",
        }.get(system, "Install it and make sure it is on PATH.")
        raise LauncherError(f"Required dependency {name!r} was not found in PATH. {install_hint}")
    return Path(found)


def check_tool(name: str) -> tuple[Path, str]:
    exe = which_required(name)
    # java prints version info to stderr; capture_command merges stderr into stdout.
    version_args = [str(exe), "-version"] if name == "java" else [str(exe), "-version"]
    result = capture_command(version_args)
    if result.returncode != 0:
        raise LauncherError(
            f"Dependency {name!r} was found at {exe}, but its version check failed "
            f"with exit code {result.returncode}: {first_output_line(result)}"
        )
    return exe, first_output_line(result)


def check_optional_tool(name: str) -> tuple[Path | None, str]:
    found = shutil.which(name)
    if not found:
        return None, "not found"
    exe = Path(found)
    result = capture_command([str(exe), "-version"])
    if result.returncode != 0:
        return exe, f"version check failed: {first_output_line(result)}"
    return exe, first_output_line(result)


def check_curses_available(system_name: str) -> None:
    try:
        import curses  # noqa: F401
    except Exception as exc:
        if system_name == "Windows":
            raise LauncherError(
                "Python curses support is not available. On Windows, install it with: "
                f"{Path(sys.executable).name} -m pip install windows-curses"
            ) from exc
        raise LauncherError(f"Python curses support is not available: {exc}") from exc


def ensure_project_layout(project_dir: Path) -> None:
    try:
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "build" / "bluray-workflow").mkdir(parents=True, exist_ok=True)
        (project_dir / "build" / "bluray-media").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise LauncherError(f"Could not create project directories under {project_dir}: {exc}") from exc
    if not project_dir.is_dir():
        raise LauncherError(f"Project path is not a directory: {project_dir}")


def preflight(project_dir: Path, *, skip_dependency_check: bool, quiet: bool) -> None:
    root = project_root()
    monitor = tui_script()
    system_name = platform.system()

    check_python()
    if not monitor.is_file():
        raise LauncherError(f"Could not find TUI script: {monitor}")

    ensure_project_layout(project_dir)
    check_curses_available(system_name)

    if not quiet:
        print(f"{APP_NAME} launcher")
        print(f"OS: {system_name} ({platform.platform()})")
        print(f"Project: {project_dir}")
        print(f"App root: {root}")

    if skip_dependency_check:
        if not quiet:
            print("Dependency check: skipped")
        return

    for tool in REQUIRED_TOOLS:
        exe, version = check_tool(tool)
        if not quiet:
            print(f"{tool}: {exe} — {version}")

    for tool in OPTIONAL_TOOLS:
        exe, version = check_optional_tool(tool)
        if not quiet:
            if exe:
                print(f"{tool}: {exe} — {version}")
            else:
                print(f"{tool}: {version} (some media analysis features may fail)")


def build_tui_command(project_dir: Path, extra_args: Iterable[str]) -> list[str]:
    return [sys.executable, str(tui_script()), str(project_dir), *list(extra_args)]


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="start.py",
        description="Launch Auto Blu-ray TUI in a cross-platform way.",
    )
    parser.add_argument(
        "project_dir",
        help='Path to the Blu-ray project directory, e.g. start.py "/path/to/project"',
    )
    parser.add_argument(
        "tui_args",
        nargs=argparse.REMAINDER,
        help="Optional arguments passed through to tools/bluray_tui_monitor.py. Use -- before pass-through args.",
    )
    parser.add_argument(
        "--skip-dependency-check",
        action="store_true",
        help="Launch without checking java/ffmpeg first.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress preflight status output before launching the TUI.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    project_dir = normalize_project_dir(args.project_dir)
    tui_args = list(args.tui_args)
    if tui_args[:1] == ["--"]:
        tui_args = tui_args[1:]

    try:
        preflight(project_dir, skip_dependency_check=args.skip_dependency_check, quiet=args.quiet)
        cmd = build_tui_command(project_dir, tui_args)
        env_pythonpath = os.environ.get("PYTHONPATH")
        if env_pythonpath:
            os.environ["PYTHONPATH"] = str(tools_dir()) + os.pathsep + env_pythonpath
        else:
            os.environ["PYTHONPATH"] = str(tools_dir())
        return stream_command(cmd, cwd=project_root())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except LauncherError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
