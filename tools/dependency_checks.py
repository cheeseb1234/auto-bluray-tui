#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
from pathlib import Path


class DependencyError(RuntimeError):
    """Raised for clean, user-facing dependency probe failures."""


TOOL_VERSION_ARGS: dict[str, tuple[str, ...]] = {
    "ffmpeg": ("-version",),
    "ffprobe": ("-version",),
    "xorriso": ("-version",),
    "libreoffice": ("--version",),
    "pdftoppm": ("-v",),
    "ant": ("-version",),
}


def capture_command(cmd: list[str], *, timeout: int = 10) -> subprocess.CompletedProcess[str]:
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
        raise DependencyError(f"Command not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DependencyError(f"Timed out while checking {cmd[0]!r}") from exc
    except OSError as exc:
        raise DependencyError(f"Failed to run {cmd[0]!r}: {exc}") from exc


def first_output_line(result: subprocess.CompletedProcess[str]) -> str:
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line:
            return line
    return "no version output"


def requests_available() -> bool:
    return importlib.util.find_spec("requests") is not None


def _java_runtime_missing_output(text: str) -> bool:
    normalized = (text or "").lower()
    return "unable to locate a java runtime" in normalized or "no java runtime present" in normalized


def _tool_candidates(name: str) -> tuple[str, ...]:
    if name == "tsMuxer":
        return ("tsMuxer", "tsMuxeR", "tsmuxer")
    return (name,)


def remediation_hint(name: str) -> str:
    system = platform.system()
    if name == "java" and system == "Darwin":
        return "brew install --cask temurin@17"
    if name == "libreoffice" and system == "Darwin":
        return "brew install --cask libreoffice"
    if name == "pdftoppm" and system == "Darwin":
        return "brew install poppler"
    if name == "ant" and system == "Darwin":
        return "brew install ant"
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
    if name == "xorriso":
        return "Install xorriso/libisoburn before burning discs."
    if name == "libreoffice":
        return "Install LibreOffice and ensure libreoffice is on PATH."
    if name == "pdftoppm":
        return "Install poppler/pdftoppm and ensure pdftoppm is on PATH."
    if name == "ant":
        return "Install Apache Ant and ensure ant is on PATH."
    if name == "udf-iso-creator":
        return "Install xorriso or a mkisofs/genisoimage/xorrisofs build with UDF support."
    return ""


def which_tool(name: str, *, root: Path | None = None, prefer_local: bool = False) -> Path | None:
    candidates = _tool_candidates(name)

    if prefer_local and root:
        local_bin = root / "tools" / "bin"
        for candidate in candidates:
            local = local_bin / candidate
            if local.exists():
                return local

    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return Path(found)
    return None


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
            except DependencyError:
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
        raise DependencyError(
            "Java is not installed. macOS found only Apple's /usr/bin/java launcher stub"
            f" at {exe}. Install a real JDK, for example: brew install --cask temurin@17"
            f". Probe output: {detail}"
        )
    raise DependencyError(
        "Required dependency 'java' was not found as a working runtime. "
        "Install a real JDK and make sure java is available via JAVA_HOME, /usr/libexec/java_home, or PATH."
    )


def _version_command(name: str, exe: Path) -> list[str]:
    if name == "tsMuxer":
        return [str(exe)]
    return [str(exe), *TOOL_VERSION_ARGS.get(name, ("-version",))]


def _render_command(cmd: list[str | Path]) -> str:
    return " ".join(str(part) for part in cmd)


def _tsmuxer_looks_usable_output(text: str) -> bool:
    return "tsmuxer" in (text or "").lower()


def _tsmuxer_platform_mismatch(text: str) -> bool:
    normalized = (text or "").lower()
    return any(
        marker in normalized
        for marker in (
            "bad cpu type in executable",
            "exec format error",
            "cannot execute binary file",
            "not a valid win32 application",
            "%1 is not a valid win32 application",
            "wrong architecture",
        )
    )


def _tsmuxer_unusable_message(detail: str, *, returncode: int | None = None) -> str:
    hint = remediation_hint("tsMuxer")
    prefix = "unusable"
    if _tsmuxer_platform_mismatch(detail):
        prefix += " — likely platform/architecture mismatch"
    elif returncode is not None:
        prefix += f" — probe failed with exit code {returncode}"
    message = f"{prefix}: {detail}"
    if hint:
        message += f" — remediation: {hint}"
    return message


def check_tool(name: str) -> tuple[Path, str]:
    exe = find_java_executable() if name == "java" else which_tool(name)
    if not exe:
        system = platform.system()
        install_hint = {
            "Windows": "Install it and make sure its bin folder is added to PATH.",
            "Darwin": "Install it with Homebrew or another package manager, then make sure it is on PATH.",
            "Linux": "Install it with your distro package manager, then make sure it is on PATH.",
        }.get(system, "Install it and make sure it is on PATH.")
        raise DependencyError(f"Required dependency {name!r} was not found in PATH. {install_hint}")

    result = capture_command(_version_command(name, exe))
    if result.returncode != 0:
        raise DependencyError(
            f"Dependency {name!r} was found at {exe}, but its version check failed "
            f"with exit code {result.returncode}: {first_output_line(result)}"
        )
    return exe, first_output_line(result)


def check_optional_tool(name: str, *, root: Path | None = None, prefer_local: bool = False) -> tuple[Path | None, str]:
    exe = which_tool(name, root=root, prefer_local=prefer_local)
    if not exe:
        hint = remediation_hint(name)
        message = "not found"
        if hint:
            message += f" — install with: {hint}"
        return None, message

    if name == "tsMuxer":
        try:
            result = capture_command(_version_command(name, exe))
        except DependencyError as exc:
            return exe, _tsmuxer_unusable_message(str(exc))

        output = (result.stdout or "").strip()
        if output and _tsmuxer_platform_mismatch(output):
            return exe, _tsmuxer_unusable_message(first_output_line(result), returncode=result.returncode)
        if output and _tsmuxer_looks_usable_output(output):
            return exe, first_output_line(result)
        if result.returncode != 0:
            return exe, _tsmuxer_unusable_message(first_output_line(result), returncode=result.returncode)
        return exe, first_output_line(result)

    result = capture_command(_version_command(name, exe))
    if result.returncode != 0:
        hint = remediation_hint(name)
        message = f"version check failed: {first_output_line(result)}"
        if hint:
            message += f" — remediation: {hint}"
        return exe, message
    return exe, first_output_line(result)


def check_udf_iso_creator(*, root: Path | None = None, prefer_local: bool = False) -> tuple[list[str] | None, str]:
    candidates: list[list[str]] = []
    unsupported: list[str] = []

    for name in ("mkisofs", "genisoimage", "xorrisofs"):
        tool = which_tool(name, root=root, prefer_local=prefer_local)
        if tool:
            candidates.append([str(tool)])

    xorriso = which_tool("xorriso", root=root, prefer_local=prefer_local)
    if xorriso:
        candidates.append([str(xorriso), "-as", "mkisofs"])

    for cmd in candidates:
        result = capture_command([*cmd, "-help"])
        text = (result.stdout or "").lower()
        if "-udf" in text or "udf" in text:
            return cmd, "supports -udf"
        unsupported.append(_render_command(cmd))

    hint = remediation_hint("udf-iso-creator")
    if unsupported:
        return None, f"found but not UDF-capable: {', '.join(unsupported)} — remediation: {hint}"
    return None, f"not found — install with: {hint}"
