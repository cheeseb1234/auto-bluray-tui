#!/usr/bin/env python3
"""Cross-platform launcher for Auto Blu-ray TUI.

This replaces scripts/monitor-bluray-project.sh as the project entry point.
It intentionally avoids shell-specific behavior so it can run on Windows,
macOS, and Linux.
"""
from __future__ import annotations

import argparse
import importlib
import os
import platform
import runpy
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from auto_bluray_tui_version import __version__

APP_NAME = "Auto Blu-ray TUI"
MIN_PYTHON = (3, 10)
REQUIRED_TOOLS = ("java", "ffmpeg")
OPTIONAL_TOOLS = ("ffprobe", "tsMuxer", "xorriso")


class LauncherError(RuntimeError):
    """Raised for clean, user-facing launcher failures."""


def project_root() -> Path:
    # In a PyInstaller onedir build, runtime data files live under sys._MEIPASS
    # (typically app/_internal). In a source checkout, they live beside start.py.
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
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


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        wanted = ".".join(str(part) for part in MIN_PYTHON)
        found = platform.python_version()
        raise LauncherError(f"Python {wanted}+ is required; found Python {found} at {sys.executable}")


def _dependency_checks():
    ensure_tools_import_path()
    return importlib.import_module("dependency_checks")


def find_java_executable() -> Path:
    deps = _dependency_checks()
    try:
        return deps.find_java_executable()
    except deps.DependencyError as exc:
        raise LauncherError(str(exc)) from exc


def which_tool(name: str) -> Path | None:
    return _dependency_checks().which_tool(name)


def remediation_hint(name: str) -> str:
    return _dependency_checks().remediation_hint(name)


def requests_available() -> bool:
    return _dependency_checks().requests_available()


def check_tool(name: str) -> tuple[Path, str]:
    deps = _dependency_checks()
    try:
        return deps.check_tool(name)
    except deps.DependencyError as exc:
        raise LauncherError(str(exc)) from exc


def check_optional_tool(name: str) -> tuple[Path | None, str]:
    return _dependency_checks().check_optional_tool(name)


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


def ensure_tools_import_path() -> None:
    tools = str(tools_dir())
    if tools not in sys.path:
        sys.path.insert(0, tools)

    env_pythonpath = os.environ.get("PYTHONPATH")
    paths = env_pythonpath.split(os.pathsep) if env_pythonpath else []
    if tools not in paths:
        os.environ["PYTHONPATH"] = tools + (os.pathsep + env_pythonpath if env_pythonpath else "")


def configure_child_python() -> None:
    os.environ.setdefault("AUTO_BLURAY_PYTHON", sys.executable)
    os.environ.setdefault("AUTO_BLURAY_APP_ROOT", str(project_root()))


def _resolve_embedded_helper(script_arg: str) -> Path | None:
    if not script_arg:
        return None
    path = Path(script_arg)
    if path.suffix.lower() != ".py":
        return None
    path = (project_root() / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        path.relative_to(project_root())
    except ValueError:
        return None
    return path if path.is_file() else None


def run_embedded_helper(script_path: Path, helper_args: Sequence[str]) -> int:
    configure_child_python()
    ensure_tools_import_path()
    old_argv = sys.argv[:]
    try:
        sys.argv = [str(script_path), *list(helper_args)]
        try:
            runpy.run_path(str(script_path), run_name="__main__")
        except SystemExit as exc:
            code = exc.code
            if code is None:
                return 0
            if isinstance(code, int):
                return code
            return 1
        return 0
    finally:
        sys.argv = old_argv


def _doctor_lines() -> list[str]:
    lines = [
        f"{APP_NAME} doctor",
        f"Version: {__version__}",
        f"OS: {platform.system()} ({platform.platform()})",
        f"Architecture: {platform.machine()}",
        f"App root: {project_root()}",
        f"Launcher python: {sys.executable}",
        f"Bundled helper python: {os.environ.get('AUTO_BLURAY_PYTHON', sys.executable)}",
        f"requests importable: {'yes' if requests_available() else 'no'}",
        "",
        "Dependency probes:",
    ]

    for name in ("java", "ffmpeg", "ffprobe", "tsMuxer", "xorriso"):
        try:
            if name in REQUIRED_TOOLS:
                exe, version = check_tool(name)
                lines.append(f"- {name}: OK — {exe} — {version}")
            else:
                exe, version = check_optional_tool(name)
                if exe:
                    lines.append(f"- {name}: OK — {exe} — {version}")
                else:
                    lines.append(f"- {name}: MISSING — {version}")
        except LauncherError as exc:
            lines.append(f"- {name}: ERROR — {exc}")

    lines += ["", "PATH:", os.environ.get("PATH", "")]
    if platform.system() == "Darwin":
        lines += [
            "",
            "Suggested macOS installs:",
            "- Java: brew install --cask temurin@17",
            "- ffmpeg/ffprobe: brew install ffmpeg",
            "- xorriso: brew install xorriso",
            "- tsMuxer: download the macOS release from https://github.com/justdan96/tsMuxer/releases and place tsMuxer/tsMuxeR on PATH",
        ]
    return lines


def print_doctor() -> int:
    configure_child_python()
    print("\n".join(_doctor_lines()))
    return 0


def _import_tui_monitor():
    ensure_tools_import_path()
    return importlib.import_module("bluray_tui_monitor")


def run_tui(project_dir: Path, extra_args: Sequence[str]) -> int:
    """Run the curses TUI in-process so PyInstaller launchers keep working."""
    configure_child_python()
    monitor = _import_tui_monitor()
    result = monitor.main([str(project_dir), *list(extra_args)])
    return 0 if result is None else int(result)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="start.py",
        description="Launch Auto Blu-ray TUI in a cross-platform way.",
    )
    parser.add_argument(
        "project_dir",
        nargs="?",
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
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Print dependency diagnostics and remediation hints, then exit.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    helper = _resolve_embedded_helper(raw_argv[0]) if raw_argv else None
    if helper:
        return run_embedded_helper(helper, raw_argv[1:])
    args = parse_args(raw_argv)
    if args.doctor:
        return print_doctor()
    if not args.project_dir:
        print("Error: project_dir is required unless --doctor is used.", file=sys.stderr)
        return 2
    project_dir = normalize_project_dir(args.project_dir)
    tui_args = list(args.tui_args)
    if tui_args[:1] == ["--"]:
        tui_args = tui_args[1:]

    try:
        preflight(project_dir, skip_dependency_check=args.skip_dependency_check, quiet=args.quiet)
        return run_tui(project_dir, tui_args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except LauncherError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
