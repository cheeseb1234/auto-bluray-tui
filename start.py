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
import importlib
import importlib.util
import runpy
import sys
from pathlib import Path
from typing import Sequence


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


def _java_runtime_missing_output(text: str) -> bool:
    normalized = (text or "").lower()
    return "unable to locate a java runtime" in normalized or "no java runtime present" in normalized


def _java_candidates() -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path | None) -> None:
        if not path:
            return
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            resolved = path.expanduser()
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(resolved)

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        add(Path(java_home) / "bin" / "java")

    if platform.system() == "Darwin":
        for cmd in (["/usr/libexec/java_home", "-v", "17"], ["/usr/libexec/java_home"]):
            try:
                result = capture_command(cmd, timeout=5)
            except LauncherError:
                continue
            if result.returncode == 0:
                home = (result.stdout or "").strip().splitlines()[0].strip()
                if home:
                    add(Path(home) / "bin" / "java")

    found = shutil.which("java")
    if found:
        add(Path(found))

    return [path for path in candidates if path.exists()]


def find_java_executable() -> Path:
    candidates = _java_candidates()
    stub_failure: tuple[Path, str] | None = None
    for exe in candidates:
        result = capture_command([str(exe), "-version"])
        if result.returncode == 0:
            return exe
        if platform.system() == "Darwin" and _java_runtime_missing_output(result.stdout or ""):
            stub_failure = (exe, first_output_line(result))
            continue
    if stub_failure:
        exe, detail = stub_failure
        raise LauncherError(
            "Java is not installed. macOS found only Apple's /usr/bin/java launcher stub"
            f" at {exe}. Install a real JDK, for example: brew install --cask temurin@17"
            f". Probe output: {detail}"
        )
    raise LauncherError(
        "Required dependency 'java' was not found as a working runtime. "
        "Install a real JDK and make sure java is available via JAVA_HOME, /usr/libexec/java_home, or PATH."
    )


def which_tool(name: str) -> Path | None:
    candidates = [name]
    if name == "tsMuxer":
        candidates = ["tsMuxer", "tsMuxeR", "tsmuxer"]
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return Path(found)
    return None


def remediation_hint(name: str) -> str:
    system = platform.system()
    if name == "java" and system == "Darwin":
        return "brew install --cask temurin@17"
    if name == "xorriso" and system == "Darwin":
        return "brew install xorriso"
    if name == "tsMuxer" and system == "Darwin":
        return "Download the macOS release from https://github.com/justdan96/tsMuxer/releases and place tsMuxer/tsMuxeR on PATH"
    if name == "ffmpeg" and system == "Darwin":
        return "brew install ffmpeg"
    if name == "ffprobe" and system == "Darwin":
        return "brew install ffmpeg"
    if name == "tsMuxer":
        return "Install tsMuxer and ensure tsMuxer, tsMuxeR, or tsmuxer is on PATH"
    return ""


def check_tool(name: str) -> tuple[Path, str]:
    if name == "java":
        exe = find_java_executable()
    else:
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
    exe = which_tool(name)
    if not exe:
        hint = remediation_hint(name)
        message = "not found"
        if hint:
            message += f" — install with: {hint}"
        return None, message
    version_cmd = [str(exe), "-version"]
    if name == "tsMuxer":
        version_cmd = [str(exe)]
    result = capture_command(version_cmd)
    if name == "tsMuxer" and (result.stdout or "").strip():
        return exe, first_output_line(result)
    if result.returncode != 0:
        hint = remediation_hint(name)
        message = f"version check failed: {first_output_line(result)}"
        if hint:
            message += f" — remediation: {hint}"
        return exe, message
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
    if not path.is_absolute():
        path = (project_root() / path).resolve()
    else:
        path = path.resolve()
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
        f"OS: {platform.system()} ({platform.platform()})",
        f"Architecture: {platform.machine()}",
        f"App root: {project_root()}",
        f"Launcher python: {sys.executable}",
        f"Bundled helper python: {os.environ.get('AUTO_BLURAY_PYTHON', sys.executable)}",
        f"requests importable: {'yes' if importlib.util.find_spec('requests') else 'no'}",
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
