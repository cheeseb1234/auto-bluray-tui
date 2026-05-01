# Auto Blu-ray TUI Release

This archive contains a platform-specific Auto Blu-ray TUI launcher, the cross-platform dependency installer (`install.py`), and bundled project support files needed by the launcher.

## Quick start

1. Run `python install.py` to install system dependencies and create `.venv`.
2. Run the bundled launcher executable with your project path:
   - Windows: `app\\auto-bluray-tui.exe C:\\path\\to\\project`
   - macOS/Linux: `./app/auto-bluray-tui /path/to/project`

## Dependency transparency

`install.py` installs or fetches heavy runtime tools used by the workflow: `ffmpeg` and Java/OpenJDK. Use `python install.py --no-system` if you already manage those dependencies yourself and only want Python environment setup.
