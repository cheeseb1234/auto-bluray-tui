# Auto Blu-ray TUI Release

This archive contains a platform-specific Auto Blu-ray TUI launcher, the cross-platform dependency installer (`install.py`), and bundled project support files needed by the launcher.

## Quick start

1. Run `python install.py` to install system dependencies and create `.venv`.
2. Run the bundled launcher executable with your project path:
   - Windows: `app\\auto-bluray-tui.exe C:\\path\\to\\project`
   - macOS/Linux: `./app/auto-bluray-tui /path/to/project`
3. If something looks off, run the built-in diagnostics first:
   - Windows: `app\\auto-bluray-tui.exe --doctor`
   - macOS/Linux: `./app/auto-bluray-tui --doctor`

## Dependency transparency

`install.py` installs or fetches heavy runtime tools used by the workflow: `ffmpeg` and Java/OpenJDK. Use `python install.py --no-system` if you already manage those dependencies yourself and only want Python environment setup.

## macOS notes

- Auto Blu-ray TUI now treats Apple's `/usr/bin/java` launcher stub as **Java missing**, not as a working Java runtime.
- Recommended Java install on macOS: `brew install --cask temurin@17`
- Recommended ISO/burn tool install on macOS: `brew install xorriso`
- macOS release archives bundle `tsMuxer` inside `app/_internal/tools/bin/tsMuxer`, and the launcher now prefers that bundled copy before anything on `PATH`.
- If you replace `tsMuxer` manually on an Intel Mac, use an `x86_64` or universal binary. The launcher will reject an arm64-only `tsMuxer`.
- Bundled workflow shell scripts prefer the packaged Python runtime via `AUTO_BLURAY_PYTHON`, so helper modules such as `requests` do not depend on the user's global `python3` site-packages.
