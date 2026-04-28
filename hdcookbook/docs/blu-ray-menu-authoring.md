# Auto Blu-ray TUI: Blu-ray Authoring Workflow

Auto Blu-ray TUI is a PowerPoint-to-Blu-ray authoring dashboard built around the HD Cook Book / BD-J / GRIN tooling. The included HD Cook Book source comes from the archived java.net project and is credited as the foundation for the menu/BD-J layer.

## Quick start

From this `hdcookbook/` directory, install/check dependencies first:

```bash
./scripts/install-bluray-deps.sh
```

To only report missing dependencies without installing anything:

```bash
./scripts/install-bluray-deps.sh --check-only
```

Then launch the full TUI workflow:

```bash
./scripts/monitor-bluray-project.sh "/home/corey/.openclaw/Bluray project"
```

For just the upstream sample build:

```bash
./scripts/build-sample-disc.sh
```

The script uses local JDK 8 + Ant if available. If not, it builds/runs a small Docker image with JDK 8 and Ant.

Expected output:

- Tools and Xlets compile under `build/`
- Sample disc overlay is zipped as `xlets/hdcookbook_discimage/HDCookbookDiscImage.zip`

Verified on Manjaro/Arch with `jdk8-openjdk` + `ant` installed. The build emits old-signing warnings because the sample BD-J signing flow uses legacy SHA-1/1024-bit test certificates, but the sample overlay still builds successfully.

The upstream sample needs the static video/disc-image base from the archived release mentioned by the Ant build. The zip produced here contains the Java/BD-J overlay that is unzipped over that base BDMV directory.

## NVIDIA GPU / NVENC acceleration

The media workflow can use NVIDIA NVENC for much faster H.264 encoding.

Check GPU/NVENC detection:

```bash
./tools/bluray_media_workflow.py "/home/corey/.openclaw/Bluray project" --gpu-status
```

On this machine it detects:

```text
NVIDIA GeForce RTX 4060 Laptop GPU, driver 590.48.01, 8188 MiB
h264_nvenc: available
hevc_nvenc: available
```

Encoding defaults to `--encoder auto`, which uses NVENC when available and CPU x264 otherwise. Explicit modes:

```bash
./scripts/prepare-bluray-media.sh "/home/corey/.openclaw/Bluray project" --encoder nvenc
./scripts/prepare-bluray-media.sh "/home/corey/.openclaw/Bluray project" --encoder cpu
```

NVENC smoke test verified with `Video 2`:

```bash
./scripts/prepare-bluray-media.sh "/home/corey/.openclaw/Bluray project" --only "Video 2" --smoke-seconds 3 --encoder nvenc
```

Output was valid 1920x1080 H.264 + AC-3 `.m2ts`, and the state file recorded `encoder: nvenc`. The TUI monitor also shows the detected GPU and active encoder per file.

## TUI progress monitor

Launch a terminal dashboard for the project:

```bash
./scripts/monitor-bluray-project.sh "/home/corey/.openclaw/Bluray project"
```

The monitor shows:

- ffmpeg/ffprobe/tsMuxer/xorriso availability
- NVIDIA/NVENC availability
- color-highlighted warnings/errors/ready states
- autopilot step progress, including the `menu.pptx` conversion step
- each video's pending/running/smoke/partial/done/failed status and progress bar
- percent complete from ffmpeg progress files
- encoded duration vs source duration
- active encoder, output size, fps, speed, bitrate, and output path
- final ISO readiness and optical burner/burn status

The monitor can now run the whole noninteractive workflow in order. Press `w` to start autopilot; it will:

1. analyze the Blu-ray project and refresh the media manifest/ffmpeg plan
2. convert `menu.pptx` into the generated GRIN menu sample
3. install/use local `tsMuxer` if it is not already available
4. encode the videos with the currently displayed TUI options
5. regenerate the Blu-ray authoring/playlist mux plan
6. build the HD Cook Book / BD-J menu overlay
7. mux each encoded title into Blu-ray `STREAM`/`CLIPINF`/`PLAYLIST` assets
8. assemble the final BDMV tree and create `bluray-project.iso`
9. if a burner and blank/appendable disc large enough for the ISO are detected, automatically burn the first disc
10. return to the TUI so the user can burn another copy or exit

Preview launchers are intentionally not part of autopilot because they open interactive GUI windows.

Controls:

- `q` quit
- `r` refresh immediately
- `w` start autopilot workflow using the currently displayed options
- `v` cycle detected optical burner device
- `b` burn the final ISO to the selected optical burner
- `k` stop the currently running encode/autopilot/burn process group
- `e` cycle encoder: `auto` / `nvenc` / `cpu`
- `z` cycle resolution: `1920x1080` / `1280x720`
- `l` cycle quality: `high` / `default` / `smaller`
- `p` cycle NVENC preset: `p4` / `p5` / `p6` / `p7`
- `a` cycle AC-3 audio bitrate: `448k` / `640k`
- `o` cycle target: all / Video 1 / Video 2 / Video 3 / Video 4
- `s` cycle smoke-test length: off / 5 / 30 / 120 seconds
- `Enter` starts encoding only with the currently displayed options

The TUI writes selected options to:

```text
/home/corey/.openclaw/Bluray project/build/bluray-media/encode-options.json
```

It now shows both overall project progress and per-task progress.

If you close and reopen the TUI while an encode is still running, it adopts the existing ffmpeg process from the state/output path and resumes showing live progress. It will also refuse to start a duplicate encode while one is already running; press `k` first if you intentionally want to stop the current run.

Autopilot status/logs are written under:

```text
/home/corey/.openclaw/Bluray project/build/bluray-workflow/
```

Final full-disc outputs are written under:

```text
/home/corey/.openclaw/Bluray project/build/final-bluray/disc-root/
/home/corey/.openclaw/Bluray project/build/final-bluray/bluray-project.iso
/home/corey/.openclaw/Bluray project/build/final-bluray/final-report.json
```

Burn status/logs are written under:

```text
/home/corey/.openclaw/Bluray project/build/bluray-burn/
```

Once the ISO exists, autopilot checks detected `/dev/sr*` burners with `xorriso -tell_media_space`. If a blank/appendable/overwriteable disc has enough capacity for the ISO, autopilot burns it automatically with `xorriso -as cdrecord` and ejects when done. The TUI then keeps running so you can insert another blank disc and press `b` to burn another copy, or press `q` to exit. Press `v` to choose a different detected burner before manual repeat burns.

For a noninteractive snapshot:

```bash
./tools/bluray_tui_monitor.py "/home/corey/.openclaw/Bluray project" --once
```

Encoder runs now write progress/state/log files under:

```text
/home/corey/.openclaw/Bluray project/build/bluray-media/logs/
```

`xorriso` is available after installing `libisoburn`, so ISO creation is unblocked once the BDMV tree exists.

## BD-25 size target

The current full-quality NVENC encodes are about 44.4 GiB total, so they require BD-50. For BD-25, re-encode with the BD-25 preset.

Project duration is about 7.87 hours. To fit single-layer BD-25 with filesystem/menu overhead, the workflow uses approximately:

- video average bitrate: `5400k`
- AC-3 audio: `448k`
- video VBV maxrate/buffer: `9000k` / `12000k`

Run from the TUI and set `disc=bd25`, or from the CLI:

```bash
./scripts/prepare-bluray-media.sh "/home/corey/.openclaw/Bluray project" --encoder nvenc --disc-preset bd25
```

This overwrites the previous oversized `.m2ts` files with BD-25-sized outputs. Expected final encoded media size is roughly 20–22 GiB before menu/BDMV overhead.

The encoder now skips existing outputs that are already acceptable for the current run. A file is considered acceptable when it probes as full-length H.264 video with 48 kHz AC-3 audio at the selected resolution; for `disc=bd25`, it must also stay under the BD-25 bitrate ceiling so older oversized quality encodes are not reused by mistake. The TUI marks files over about 7.2 Mb/s container bitrate as `oversized` instead of `done`. To intentionally redo everything, add:

```bash
--force-reencode
```

## Authoring handoff: playlist map and mux plan

After converting the PowerPoint menu and analyzing media, generate the current Blu-ray authoring handoff plan:

```bash
./scripts/create-bluray-authoring-plan.sh "/home/corey/.openclaw/Bluray project"
```

Outputs:

```text
/home/corey/.openclaw/Bluray project/build/bluray-authoring/playlist-map.json
/home/corey/.openclaw/Bluray project/build/bluray-authoring/mux-plan.md
/home/corey/.openclaw/Bluray project/build/bluray-authoring/tsmuxer-meta/*.meta
```

After all encoded files are BD-25 acceptable, assemble the final tree and ISO:

```bash
./scripts/create-final-bluray-iso.sh "/home/corey/.openclaw/Bluray project"
```

Outputs:

```text
/home/corey/.openclaw/Bluray project/build/final-bluray/disc-root/
/home/corey/.openclaw/Bluray project/build/final-bluray/bluray-project.iso
/home/corey/.openclaw/Bluray project/build/final-bluray/final-report.json
```

This assigns stable IDs for the menu buttons:

- `Video 1` → playlist/title `00001`
- `Video 2` → playlist/title `00002`
- `Video 3` → playlist/title `00003`
- `Video 4` → playlist/title `00004`

The PowerPoint-generated GRIN now includes a generated Java hook:

```java
playVideo(videoFile, playlistId)
```

In GRINView it logs `PPTX_MENU_PLAY ...`. In the final BD-J Xlet, this is the clean replacement point for real playlist/title navigation.

The mux plan checks whether encoded `.m2ts` files are full-length or only smoke-test clips. The current `Video 2.m2ts` is intentionally detected as partial because it was a 5-second smoke test.

## Media preparation with ffmpeg

The PowerPoint conversion handles menu pages and button regions. The next workflow prepares the linked videos for Blu-ray-style playback.

Analyze the project folder and write a manifest/ffmpeg plan:

```bash
./scripts/analyze-bluray-project.sh "/home/corey/.openclaw/Bluray project"
```

Outputs:

```text
/home/corey/.openclaw/Bluray project/build/bluray-media/media-manifest.json
/home/corey/.openclaw/Bluray project/build/bluray-media/ffmpeg-plan.md
```

Prepare video streams:

```bash
./scripts/prepare-bluray-media.sh "/home/corey/.openclaw/Bluray project"
```

Smoke-test one file without doing a full multi-hour encode:

```bash
./scripts/prepare-bluray-media.sh "/home/corey/.openclaw/Bluray project" --only "Video 2" --smoke-seconds 5
```

The encoder normalizes video to 1920x1080 H.264 + AC-3 in `.m2ts` containers:

- scales/pads wide sources to 16:9 1080p
- keeps 23.976 fps
- uses `libx264` with Blu-ray compatibility flags
- converts audio to 48 kHz AC-3
- records sidecar `.srt` subtitle mapping in the manifest

Smoke test verified: `Video 2` produced a valid 5-second `encoded/Video 2.m2ts`.

Tooling status on this machine:

- available: `ffmpeg`, `ffprobe`, `java`, `ant`, `libreoffice`, `pdftoppm`
- missing: `tsMuxer`, `xorriso`/`mkisofs`, `mediainfo`, `bdsup2sub`

For final selectable Blu-ray subtitles, SRT must become PGS/SUP or be burned into video. This workflow preserves subtitle mapping now; mux/authoring integration comes next.

### tsMuxer local install

Fetch the official Linux tsMuxer release locally into `tools/bin/`:

```bash
./scripts/get-tsmuxer.sh
```

The script downloads `tsMuxer-2.7.0-linux.zip` from `justdan96/tsMuxer`, extracts `tsMuxeR`, and installs it as:

```text
tools/bin/tsMuxer
```

This path is intentionally gitignored so the repository does not commit third-party binaries. `create-bluray-authoring-plan.sh` checks this local binary before checking system `PATH`.

Verified locally with the 5-second `Video 2.m2ts` smoke encode; tsMuxer detects:

- H.264 High@4.1, 1920x1080p, 23.976 fps
- AC-3 640 kbps, 48 kHz

## PowerPoint-first workflow

For non-technical menu authoring, use a normal `.pptx` file as the menu source.

Current project source:

```text
/home/corey/.openclaw/Bluray project/menu.pptx
```

Convert it into a GRIN menu sample:

```bash
./scripts/convert-pptx-menu.sh "/home/corey/.openclaw/Bluray project"
```

Preview it:

```bash
./scripts/launch-pptx-menu-preview.sh
```

The converter currently reads:

- PowerPoint slide backgrounds via LibreOffice/PDF export
- PowerPoint hyperlink buttons for slide-to-slide navigation
- `Video 1`, `Video 2`, etc. text buttons and maps them to matching video files in the project folder
- `.srt` subtitle files in the project folder for later playlist/subtitle muxing

Generated menu sample:

```text
xlets/grin_samples/Scripts/PptxMenu
```

Validated with `ant autotest`. Video buttons currently preview as activation feedback; the next integration layer maps those actions to actual Blu-ray playlists/titles.

## Second version: PowerPoint-style slide menu

A separate slide-based menu sample is available at:

```text
xlets/grin_samples/Scripts/SlidesMenu
```

This keeps the original HD Cookbook disc-image sample untouched. The slide menu is generated from `slides.json`:

- each slide is a menu page
- slides have titles, subtitles, body text, custom background colors, and accent colors
- buttons have labels, targets, and screen rectangles
- the generator emits GRIN `slides-menu.txt` plus PNG backgrounds/button focus overlays

Preview it with:

```bash
./scripts/launch-slides-menu-preview.sh
```

Or from the sample directory:

```bash
cd xlets/grin_samples/Scripts/SlidesMenu
ant preview
```

Validated with `ant autotest`; it builds `build/00000.jar` and passes GRINView automation. The template uses 1280x720 graphics by default to stay under old BD-J/GRIN image-memory limits while preserving 16:9 layout.

## Preview the menu GUI

Launch the Swing-based GRINView previewer:

```bash
./scripts/launch-menu-preview.sh
```

GRINView is not a full Blu-ray player emulator, but it is the fastest way to iterate on menu layout, focus movement, button states, and GRIN show scripting before burning or muxing a disc image.

## Where the interactive menu lives

Main sample menu files:

- `xlets/hdcookbook_discimage/bookmenu/src/com/hdcookbook/bookmenu/assets/menu.txt` — GRIN menu/show script
- `xlets/hdcookbook_discimage/bookmenu/src/com/hdcookbook/bookmenu/assets/mosaics.txt` — image mosaic packing config
- `xlets/hdcookbook_discimage/bookmenu/src/com/hdcookbook/bookmenu/menu/MenuXlet.java` — BD-J Xlet entry point
- `xlets/hdcookbook_discimage/bookmenu/src/com/hdcookbook/bookmenu/menu/MenuDirector.java` — menu logic/director
- `xlets/hdcookbook_discimage/bookmenu/src/com/hdcookbook/bookmenu/menu/MenuDiscNavigator.java` — playlist/title navigation glue

The important build flow is:

1. `menu.txt` is compiled by the GRIN binary converter.
2. Generated Java lands under `build/xlets/menu_generated/`.
3. The menu Xlet is packaged as `BDMV/JAR/00002.jar`.
4. BDJO/BDMV metadata is generated and the Xlets are signed.
5. The overlay BDMV tree is zipped.

## Practical editing path

For a custom disc menu, start by copying the existing `bookmenu` sample rather than writing a BD-J Xlet from scratch.

Recommended first pass:

1. Replace menu artwork in the `assets/Graphics/` tree.
2. Edit labels and segments in `assets/menu.txt`.
3. Keep the existing remote-control handlers until the first build works.
4. Adjust `MenuDiscNavigator.java` only after the visual menu compiles.
5. Build with `./scripts/build-sample-disc.sh` after each meaningful change.

## Local prerequisites

HD Cook Book is old BD-J code. It is happiest with:

- JDK 8
- Apache Ant
- BD-J platform stubs

The archived repository already contains BD-J stub classes at:

```text
lib/stubs/enhanced/classes.zip
```

`user.vars.properties.example` points the build at those stubs. The build script copies it to `user.vars.properties` automatically when needed.
