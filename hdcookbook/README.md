# Auto Blu-ray TUI

Auto Blu-ray TUI is a practical Blu-ray authoring workflow built on top of the archived HD Cook Book / BD-J / GRIN tooling.

Instead of hand-running a long chain of conversion, encoding, muxing, ISO, and burn commands, the project provides a single terminal dashboard that can automatically work through the whole process.

## What Auto Blu-ray TUI does

The TUI/autopilot workflow can:

1. analyze a project folder of videos/subtitles
2. process `menu.pptx` into generated GRIN menu assets
3. encode Blu-ray-compatible H.264 + AC-3 `.m2ts` files
4. use NVIDIA NVENC/RTX acceleration automatically when available
5. enforce BD-25 sizing guardrails
6. skip existing acceptable encodes instead of wasting time
7. build the HD Cook Book BD-J menu overlay
8. mux final Blu-ray title assets
9. assemble a final Blu-ray ISO
10. detect optical burners and blank media
11. burn the finished ISO, then prompt to burn another copy or exit

## Install dependencies

From this `hdcookbook/` directory:

```bash
./scripts/install-bluray-deps.sh
```

Check-only mode:

```bash
./scripts/install-bluray-deps.sh --check-only
```

The installer handles common Linux/macOS package managers where possible and installs/checks tools such as:

- Python 3
- ffmpeg / ffprobe
- LibreOffice
- Poppler / `pdftoppm`
- Java / Ant
- xorriso / libisoburn
- curl / unzip
- local tsMuxer

## Launch the TUI

```bash
./scripts/monitor-bluray-project.sh "/path/to/Blu-ray project"
```

Example:

```bash
./scripts/monitor-bluray-project.sh "/home/corey/.openclaw/Bluray project"
```

Main controls:

- `w` — start full autopilot
- `Enter` — encode only
- `b` — burn final ISO to selected optical burner
- `v` — cycle detected burners
- `k` — stop running encode/autopilot/burn process
- `q` — quit

The TUI shows color-highlighted status, per-step progress, per-video progress, final ISO readiness, and burner/media status.

## Outputs

Build products are written inside the source media project folder:

```text
build/bluray-media/        encoded video, logs, manifests
build/bluray-authoring/    playlist maps and mux plans
build/final-bluray/        final BDMV tree and ISO
build/bluray-burn/         burn logs/state
```

Final ISO:

```text
build/final-bluray/bluray-project.iso
```

## Recommended project layout

```text
menu.pptx
Video 1.mkv
Video 1.srt
Video 2.mp4
Video 2.srt
Video 3.mkv
Video 3.srt
Video 4.mp4
Video 4.srt
```

PowerPoint button labels like `Video 1`, `Video 2`, etc. are mapped to matching media files.

If a video has no matching sidecar subtitle, autopilot can try OpenSubtitles before media analysis. Set `OPENSUBTITLES_API_KEY`, `OPENSUBTITLES_USERNAME`, and `OPENSUBTITLES_PASSWORD` in the environment; optional `OPENSUBTITLES_LANGUAGE` defaults to `en`. If credentials are missing, the lookup is skipped safely and the TUI reports it as an informational preflight note.

## More documentation

Start here:

```text
docs/walkthrough.md
```

Detailed notes:

```text
docs/blu-ray-menu-authoring.md
```

## Credits / upstream heritage

Auto Blu-ray TUI includes the HD Cook Book java.net project archive, version 1.2, as its BD-J/GRIN foundation. Credit goes to the original HD Cook Book authors for that base. The Auto Blu-ray TUI project adds the automated PowerPoint-to-Blu-ray dashboard, media preparation, ISO assembly, and burn workflow.
