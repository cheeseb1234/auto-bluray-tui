# Auto Blu-ray TUI

A practical, terminal-first workflow for turning a folder of videos plus a PowerPoint menu into a Blu-ray-ready project, final ISO, and optional burned disc.

Auto Blu-ray TUI (terminal user interface) is its own project. It includes and builds on the archived HD Cook Book / BD-J / GRIN tooling, but the user-facing goal is a modern automated Blu-ray authoring dashboard.

Instead of learning a complex authoring program or paying for expensive alternatives, design your disc menu in PowerPoint.

## What it does

Auto Blu-ray TUI guides the whole disc-building process from one dashboard:

1. scans a project folder for videos and subtitles
2. converts `menu.pptx` into a Blu-ray menu structure
3. prepares Blu-ray-compatible H.264 + AC-3 `.m2ts` media
4. uses NVIDIA NVENC automatically when available, with CPU fallback
5. targets DVD-5, DVD-9, BD-25, or quality/no-cap output depending on the selected disc preset
6. builds the HD Cook Book BD-J menu overlay
7. muxes titles into Blu-ray `STREAM`, `CLIPINF`, and `PLAYLIST` assets
8. assembles a final Blu-ray ISO
9. detects an optical burner and blank disc
10. burns the first disc automatically when media is large enough, then lets you burn more copies or exit

<img width="2520" height="1104" alt="Screenshot_20260429_162310" src="https://github.com/user-attachments/assets/18199d27-90fc-4093-8de4-a17c8f15119e" />
<img width="2520" height="1104" alt="Screenshot_20260429_162310" src="https://github.com/user-attachments/assets/639aaf93-e7f4-4d89-af89-cab0546704cb" />

## Why it is useful

Blu-ray authoring normally involves a fragile chain of tools and formats. This project wraps that chain in a single TUI that shows what is happening, where it failed, and what is safe to reuse.

Benefits:

- **PowerPoint-first menus** — build menu screens in a familiar editor instead of hand-authoring every layout. Shapes whose text matches a video, such as `Background 1`, can become autoplaying looped video regions on that slide.
- **One-command workflow** — launch the TUI and let autopilot work through the steps.
- **GPU acceleration** — uses RTX/NVENC automatically when available.
- **Disc-size guardrails** — targets DVD-5, DVD-9, or BD-25 and rejects oversized encodes/ISOs instead of silently creating output that will not fit.
- **Resume-friendly behavior** — skips acceptable existing encodes and adopts already-running ffmpeg jobs when relaunched.
- **Visible progress** — color status, per-step progress bars, per-video progress, ISO readiness, and burner status.
- **Disc burning loop** — burn the finished ISO, insert another blank disc, burn again, or exit.

## Quick start

From the repository root:

```bash
./scripts/install-bluray-deps.sh
./scripts/monitor-bluray-project.sh "/path/to/Blu-ray project"
```

When the TUI opens, it runs an initial project/media analysis before the dashboard so you can see the video/subtitle inventory before choosing a workflow.

In the TUI:

- **Actions:** `w` full autopilot, `Enter` encode media only, `b` burn the final ISO, `k` stop running work, `q` quit
- **View/device:** `r` refresh/re-analyze if needed, `v` cycle detected optical burners
- **Options:** `d` disc size (`DVD-5` → `DVD-9` → `BD-25` → quality/no cap), `e` encoder, `z` resolution, `l` quality, `p` NVENC preset, `a` audio bitrate, `o` encode only one video, `s` smoke-test length

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

If a video has no matching sidecar subtitle, autopilot can try OpenSubtitles before media analysis. Set these environment variables first:

```bash
export OPENSUBTITLES_API_KEY='your-api-key'
export OPENSUBTITLES_USERNAME='your-username'
export OPENSUBTITLES_PASSWORD='your-password'
# optional; default is English
export OPENSUBTITLES_LANGUAGE='en'
```

Without those credentials the lookup is skipped safely and the TUI shows an informational preflight note.

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

- [docs/walkthrough.md](https://github.com/cheeseb1234/auto-bluray-tui/blob/main/docs/walkthrough.md)

Detailed workflow notes live here:

- [docs/blu-ray-menu-authoring.md](https://github.com/cheeseb1234/auto-bluray-tui/blob/main/docs/blu-ray-menu-authoring.md)

## Credits / upstream heritage

Auto Blu-ray TUI includes and builds on the archived HD Cook Book / java.## Intended use

This project is for authoring Blu-ray discs from your own videos, personal projects,
home movies, training materials, or other content you have the right to use.

It does not decrypt commercial Blu-ray discs, remove copy protection, or assist with
unauthorized copying of copyrighted material.net source tree. HD Cook Book remains the BD-J/GRIN foundation and reference implementation; this project adds the automated PowerPoint-to-Blu-ray TUI workflow, media preparation, ISO assembly, and burn automation around it.

## Intended use

This project is for authoring Blu-ray discs from your own videos, personal projects,
home movies, training materials, or other content you have the right to use.

It does not decrypt commercial Blu-ray discs, remove copy protection, or assist with
unauthorized copying of copyrighted material.

Find this useful? Feel free to donate https://buymeacoffee.com/rarecore
