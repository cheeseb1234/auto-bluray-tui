# Auto Blu-ray TUI

A practical, terminal-first workflow for turning a folder of videos plus a PowerPoint menu into a Blu-ray-ready project, final ISO, and optional burned disc.

Auto Blu-ray TUI (terminal user interface)is its own project. It includes and builds on the archived HD Cook Book / BD-J / GRIN tooling, but the user-facing goal is a modern automated Blu-ray authoring dashboard.

Instead of learning and navigating a complex program or paying for expensive other options, just use design your disc menu in powerpoint!

## What it does

Auto Blu-ray TUI guides the whole disc-building process from one dashboard:

1. scans a project folder for videos and subtitles
2. converts `menu.pptx` into a Blu-ray menu structure
3. prepares Blu-ray-compatible H.264 + AC-3 `.m2ts` media
4. uses NVIDIA NVENC automatically when available, with CPU fallback
5. targets BD-25 sizing so the finished project fits common 25 GB Blu-ray media
6. builds the HD Cook Book BD-J menu overlay
7. muxes titles into Blu-ray `STREAM`, `CLIPINF`, and `PLAYLIST` assets
8. assembles a final Blu-ray ISO
9. detects an optical burner and blank disc
10. burns the first disc automatically when media is large enough, then lets you burn more copies or exit

## Why it is useful

Blu-ray authoring normally involves a fragile chain of tools and formats. This project wraps that chain in a single TUI that shows what is happening, where it failed, and what is safe to reuse.

Benefits:

- **PowerPoint-first menus** — build menu screens in a familiar editor instead of hand-authoring every layout.
- **One-command workflow** — launch the TUI and let autopilot work through the steps.
- **GPU acceleration** — uses RTX/NVENC automatically when available.
- **BD-25 guardrails** — rejects oversized encodes instead of silently creating an ISO that will not fit.
- **Resume-friendly behavior** — skips acceptable existing encodes and adopts already-running ffmpeg jobs when relaunched.
- **Visible progress** — color status, per-step progress bars, per-video progress, ISO readiness, and burner status.
- **Disc burning loop** — burn the finished ISO, insert another blank disc, burn again, or exit.

## Quick start

From the `hdcookbook/` directory:

```bash
./scripts/install-bluray-deps.sh
./scripts/monitor-bluray-project.sh "/path/to/Blu-ray project"
```

In the TUI:

- `w` starts full autopilot
- `Enter` starts encode-only
- `b` burns the final ISO to the selected burner
- `v` cycles detected optical burners
- `k` stops running encode/autopilot/burn work
- `q` exits

## Project folder expectations

A project folder can contain:

```text
menu.pptx
Video 1.mkv
Video 1.srt
Video 2.mp4
Video 2.srt
...
```

The workflow writes build outputs under:

```text
build/bluray-media/
build/bluray-authoring/
build/final-bluray/
build/bluray-burn/
```

The final ISO is written to:

```text
build/final-bluray/bluray-project.iso
```

## Documentation

Start with the walkthrough:

```text
hdcookbook/docs/walkthrough.md
```

Detailed workflow notes live here:

```text
hdcookbook/docs/blu-ray-menu-authoring.md
```

## Credits / upstream heritage

Auto Blu-ray TUI includes and builds on the archived HD Cook Book / java.net source tree. HD Cook Book remains the BD-J/GRIN foundation and reference implementation; this project adds the automated PowerPoint-to-Blu-ray TUI workflow, media preparation, ISO assembly, and burn automation around it.

Find this useful? Feel free to donate https://buymeacoffee.com/rarecore
