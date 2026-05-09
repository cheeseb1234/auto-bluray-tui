#!/usr/bin/env python3
"""Cross-platform optical-disc burning abstraction for Auto Blu-ray TUI.

The public surface is intentionally small:

    burner = Burner()
    drive = burner.detect_drive()
    ok = burner.burn_iso("/path/to/disc.iso")

Each OS uses a dedicated strategy internally so platform-specific behavior stays
contained and testable.
"""
from __future__ import annotations

import argparse
import logging
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Drive:
    """Detected optical drive information."""

    device: str
    label: str = ""
    backend: str = ""

    def __str__(self) -> str:
        return f"{self.device} ({self.label})" if self.label else self.device


class BurnStrategy:
    """Base class for OS-specific burning strategies."""

    name = "generic"

    def __init__(self, preferred_drive: str | None = None) -> None:
        self.preferred_drive = preferred_drive

    def detect_drive(self) -> Drive | None:
        raise NotImplementedError

    def burn_iso(self, iso_path: Path) -> bool:
        raise NotImplementedError

    @staticmethod
    def _stream(cmd: Sequence[str]) -> bool:
        """Run a command while streaming stdout/stderr directly to the console."""
        print("+ " + " ".join(str(part) for part in cmd), flush=True)
        try:
            proc = subprocess.Popen(
                list(cmd),
                stdout=sys.stdout,
                stderr=sys.stderr,
                stdin=subprocess.DEVNULL,
                text=True,
            )
            return proc.wait() == 0
        except FileNotFoundError:
            print(f"Burn command not found: {cmd[0]}", file=sys.stderr)
            return False
        except OSError as exc:
            print(f"Failed to start burn command {cmd[0]!r}: {exc}", file=sys.stderr)
            return False

    @staticmethod
    def _capture(cmd: Sequence[str], *, timeout: int = 10) -> subprocess.CompletedProcess[str] | None:
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
        except Exception:
            return None


class LinuxBurnStrategy(BurnStrategy):
    """Linux implementation using wodim/cdrecord against /dev/sr* devices."""

    name = "linux"

    def _burn_command(self) -> str | None:
        return shutil.which("wodim") or shutil.which("cdrecord")

    def _linux_drive_label(self, dev: str) -> str:
        name = PurePosixPath(dev).name
        parts: list[str] = []
        for field in ("vendor", "model"):
            try:
                value = (Path("/sys/block") / name / "device" / field).read_text(errors="ignore").strip()
            except OSError:
                value = ""
            if value:
                parts.append(value)
        return " ".join(parts) or name

    def detect_drive(self) -> Drive | None:
        if self.preferred_drive:
            return Drive(self.preferred_drive, self._linux_drive_label(self.preferred_drive), self.name)

        candidates = sorted(Path("/dev").glob("sr*"))
        if not candidates:
            # Requirement default: target /dev/sr0. Return it as a best guess so
            # callers get a clear burn-command failure instead of no-op silence.
            fallback = "/dev/sr0"
            return Drive(fallback, "default optical drive", self.name)

        dev = str(candidates[0])
        return Drive(dev, self._linux_drive_label(dev), self.name)

    def burn_iso(self, iso_path: Path) -> bool:
        burner = self._burn_command()
        if not burner:
            print("Neither wodim nor cdrecord was found in PATH.", file=sys.stderr)
            print("Install wodim/cdrkit or cdrtools, then retry.", file=sys.stderr)
            return False

        drive = self.detect_drive()
        if not drive:
            print("No Linux optical drive detected.", file=sys.stderr)
            return False

        # wodim/cdrecord print useful burn progress to stderr/stdout themselves.
        return self._stream([burner, "-v", f"dev={drive.device}", "-eject", str(iso_path)])


class MacOSBurnStrategy(BurnStrategy):
    """macOS implementation using the native drutil command."""

    name = "macos"

    def detect_drive(self) -> Drive | None:
        drutil = shutil.which("drutil")
        if not drutil:
            return None

        if self.preferred_drive:
            return Drive(self.preferred_drive, "preferred drive", self.name)

        result = self._capture([drutil, "status"])
        label = "optical drive"
        if result and result.stdout:
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped and not stripped.lower().startswith("vendor"):
                    label = stripped[:80]
                    break
        return Drive("drutil", label, self.name)

    def burn_iso(self, iso_path: Path) -> bool:
        drutil = shutil.which("drutil")
        if not drutil:
            print("drutil was not found. This does not look like a standard macOS environment.", file=sys.stderr)
            return False
        # drutil streams burn/verification progress to the terminal.
        return self._stream([drutil, "burn", str(iso_path)])


class WindowsBurnStrategy(BurnStrategy):
    """Windows implementation using ImgBurn when available, then native isoburn.

    Windows does not ship a reliable PowerShell cmdlet equivalent to macOS
    `drutil burn`. IMAPI2 can be driven through COM, but ISO-image streaming is
    fragile from plain PowerShell. ImgBurn's CLI is the practical automated path.
    `isoburn.exe` is kept as a native fallback, but it may open UI and may not
    provide useful console progress.
    """

    name = "windows"

    def _imgburn_candidates(self) -> Iterable[Path]:
        path_hit = shutil.which("ImgBurn.exe") or shutil.which("ImgBurn")
        if path_hit:
            yield Path(path_hit)

        env_roots = [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")]
        for root in env_roots:
            if root:
                yield Path(root) / "ImgBurn" / "ImgBurn.exe"

        # Explicit common defaults requested by the app requirements. Keep these
        # even when tests/nonstandard shells do not populate ProgramFiles vars.
        yield Path(r"C:\Program Files (x86)\ImgBurn\ImgBurn.exe")
        yield Path(r"C:\Program Files\ImgBurn\ImgBurn.exe")

    def _imgburn(self) -> Path | None:
        for candidate in self._imgburn_candidates():
            if candidate.is_file():
                return candidate
        return None

    def _isoburn(self) -> Path | None:
        windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT")
        candidates: list[Path] = []
        hit = shutil.which("isoburn.exe")
        if hit:
            candidates.append(Path(hit))
        if windir:
            candidates.append(Path(windir) / "System32" / "isoburn.exe")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def _native_drive_letter(self) -> str | None:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
        if powershell:
            result = self._capture([
                powershell,
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_CDROM | Where-Object { $_.Drive } | Select-Object -First 1 -ExpandProperty Drive",
            ])
            if result and result.returncode == 0:
                for line in result.stdout.splitlines():
                    drive = line.strip()
                    if len(drive) >= 2 and drive[1] == ":":
                        return drive[:2]

        wmic = shutil.which("wmic.exe") or shutil.which("wmic")
        if wmic:
            result = self._capture([wmic, "cdrom", "get", "drive"], timeout=10)
            if result and result.returncode == 0:
                for line in result.stdout.splitlines():
                    drive = line.strip()
                    if len(drive) >= 2 and drive[1] == ":":
                        return drive[:2]

        return None

    def detect_drive(self) -> Drive | None:
        if self.preferred_drive:
            return Drive(self.preferred_drive, "preferred drive", self.name)

        drive = self._native_drive_letter()
        if drive:
            return Drive(drive, "Windows optical drive", self.name)

        if self._imgburn() or self._isoburn():
            return Drive("D:", "default Windows optical drive", self.name)
        return None

    def burn_iso(self, iso_path: Path) -> bool:
        drive = self.detect_drive()
        if not drive:
            print("No Windows optical drive detected.", file=sys.stderr)
            return False

        imgburn = self._imgburn()
        if imgburn:
            # ImgBurn provides the most automatable Windows burn path and reports
            # useful progress through its own process/log window.
            return self._stream([
                str(imgburn),
                "/MODE", "WRITE",
                "/SRC", str(iso_path),
                "/DEST", drive.device,
                "/START",
                "/CLOSESUCCESS",
            ])

        isoburn = self._isoburn()
        if isoburn:
            # Native fallback: isoburn.exe may launch a background GUI and does
            # not provide rich console progress metrics. Prefer ImgBurn when
            # silent/observable automation matters.
            LOGGER.warning(
                "Falling back to Windows isoburn.exe; it may launch a background GUI "
                "and will not provide rich console progress metrics."
            )
            return self._stream([str(isoburn), "/Q", drive.device, str(iso_path)])

        print("No supported Windows ISO burner was found.", file=sys.stderr)
        print("Install ImgBurn and make sure ImgBurn.exe is in PATH, or use Windows' built-in Disc Image Burner manually.", file=sys.stderr)
        print("ImgBurn: https://www.imgburn.com/", file=sys.stderr)
        return False


class UnsupportedBurnStrategy(BurnStrategy):
    name = "unsupported"

    def detect_drive(self) -> Drive | None:
        return None

    def burn_iso(self, iso_path: Path) -> bool:
        print(f"Unsupported OS for optical burning: {platform.system()}", file=sys.stderr)
        return False


class Burner:
    """OS-aware optical burner facade.

    Parameters:
        preferred_drive: optional OS-specific drive/device override.
            Linux examples: /dev/sr0, /dev/sr1
            Windows ImgBurn example: E:
    """

    def __init__(self, preferred_drive: str | None = None) -> None:
        self.preferred_drive = preferred_drive
        self.system = platform.system()
        self.strategy = self._make_strategy(self.system, preferred_drive)

    @staticmethod
    def _make_strategy(system_name: str, preferred_drive: str | None) -> BurnStrategy:
        if system_name == "Linux":
            return LinuxBurnStrategy(preferred_drive)
        if system_name == "Darwin":
            return MacOSBurnStrategy(preferred_drive)
        if system_name == "Windows":
            return WindowsBurnStrategy(preferred_drive)
        return UnsupportedBurnStrategy(preferred_drive)

    def detect_drive(self) -> Drive | None:
        """Return the best detected drive for the current OS, or None."""
        return self.strategy.detect_drive()

    def burn_iso(self, iso_path: str | Path) -> bool:
        """Burn an ISO image. Returns True on success, False on failure."""
        iso = Path(iso_path).expanduser().resolve()
        if not iso.is_file():
            print(f"ISO file not found: {iso}", file=sys.stderr)
            return False
        return self.strategy.burn_iso(iso)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Burn an ISO image to an optical disc.")
    parser.add_argument("iso", nargs="?", help="ISO image to burn")
    parser.add_argument("--drive", help="Preferred drive/device, e.g. /dev/sr0 or E:")
    parser.add_argument("--detect", action="store_true", help="Only detect and print the selected drive")
    args = parser.parse_args(argv)

    burner = Burner(preferred_drive=args.drive)
    drive = burner.detect_drive()

    if args.detect:
        if drive:
            print(f"Detected drive: {drive} [{drive.backend}]")
            return 0
        print("No optical drive detected.", file=sys.stderr)
        return 1

    if not args.iso:
        parser.error("iso is required unless --detect is used")

    if drive:
        print(f"Using drive: {drive} [{drive.backend}]", flush=True)
    else:
        print("No optical drive detected; attempting burn backend anyway.", file=sys.stderr)

    return 0 if burner.burn_iso(args.iso) else 1


if __name__ == "__main__":
    raise SystemExit(main())
