# Auto Blu-ray TUI: Notes for Blu-ray Authoring

Auto Blu-ray TUI is a PowerPoint-to-Blu-ray authoring dashboard built around the archived HD Cook Book / BD-J / GRIN tooling. HD Cook Book remains the BD-J/GRIN foundation; Auto Blu-ray TUI adds the project analyzer, PowerPoint converter, media encoder, playlist planner, ISO builder, burner workflow, and safety checks.

## Current end-to-end flow

From the repository root:

```bash
./scripts/install-bluray-deps.sh
./scripts/monitor-bluray-project.sh "/path/to/project"
```

Inside the TUI, press `w` for autopilot. The current workflow order is:

1. `fetch-opensubtitles` — downloads missing sidecar subtitles when OpenSubtitles credentials are configured; otherwise skips safely.
2. `analyze` — probes project videos/subtitles and writes `build/bluray-media/media-manifest.json`.
3. `convert-pptx-menu` — converts `menu.pptx` into generated GRIN/BD-J assets.
4. `get-tsmuxer` — installs/uses a local tsMuxer when needed.
5. `prepare-bluray-media` — encodes linked titles and generated menu-loop clips to Blu-ray-friendly H.264 + AC-3 `.m2ts`.
6. `create-bluray-authoring-plan` — maps menu actions to playlist IDs and writes mux templates.
7. `build-sample-disc` — builds the HD Cook Book BD-J overlay.
8. `create-final-bluray-iso` — muxes titles, patches playlist/clip IDs, creates BDMV tree and ISO.
9. `auto-burn-final-bluray` — burns the first disc when a suitable blank/appendable disc is present.

The TUI also runs an initial non-destructive analysis before showing the dashboard when the manifest is missing or stale.

## Recommended project layout

```text
project/
├── menu.pptx
├── Main Feature.mkv
├── Main Feature.srt
├── Bonus Feature.mp4
├── Background 1.mp4
└── Background 2.mp4
```

Generated outputs stay under `project/build/`:

```text
build/bluray-media/        manifests, ffmpeg plan, encoded .m2ts files, logs
build/bluray-authoring/    playlist-map.json, mux-plan.md, tsMuxer meta files
build/pptx-menu-loops/     generated per-slide loop source clips
build/final-bluray/        final BDMV tree, ISO, final-report.json
build/bluray-burn/         burn options/state/logs
```

## PowerPoint menu conversion

Convert manually:

```bash
./scripts/convert-pptx-menu.sh "/path/to/project"
```

Generated menu sample:

```text
xlets/grin_samples/Scripts/PptxMenu/
```

Important generated files:

```text
menu-model.json          backend-neutral model: slides, backgrounds, buttons, hitboxes,
                         focus order, actions, playlists, video targets, requirements
menu-compatibility.json  machine-readable HDMV-vs-BD-J compatibility report
menu-compatibility.md    human-readable compatibility report
video-actions.json       button + loop playlist actions
loop-actions.json        loop playlist actions only
pptx-menu.txt            generated GRIN script for the BD-J backend
assets/*.png             slide backgrounds and button state overlays
```

## Menu backends: HDMV, BD-J, and auto

Auto Blu-ray TUI now separates PowerPoint parsing from Blu-ray menu authoring. The converter first emits a backend-neutral `menu-model.json`, then a backend selector chooses how to author that model.

Backend values:

- `hdmv` — default. Validates that the model uses only the current HDMV-Lite-safe feature subset, then fails clearly because actual HDMV compilation is not implemented yet.
- `bdj` — current production path. Builds the generated GRIN script and installs/signs the BD-J Xlet/JAR/BDJO artifacts.
- `auto` — chooses `hdmv` when the compatibility report is HDMV-safe; otherwise falls back to `bdj` when BD-J-only features are detected.

Use BD-J for working discs today:

```bash
./scripts/create-final-bluray-iso.sh "/path/to/project" --menu-backend bdj
```

The TUI persists the same setting in `build/bluray-media/encode-options.json`; press `m` to cycle `hdmv` / `bdj` / `auto`.

### Current HDMV-Lite status

The HDMV backend now implements the first conservative HDMV-Lite milestone. It accepts HDMV-safe neutral menu models and emits a Java-free HDMV-Lite authoring package under `build/final-bluray/hdmv-lite/` containing:

- `hdmv-lite-menu.json` static menu/page/button/action IR
- copied static background assets
- `index.xml` and `MovieObject.xml` skeletons
- `index.bdmv` / `MovieObject.bdmv` when the bundled DiscCreationTools converters are available

This is still not a full Interactive Graphics compiler. The generated package proves the static menu model, hitboxes, and simple actions are representable; final IG stream and HDMV command bytecode compilation are the next milestone.

HDMV-Lite accepted in the current model:

- static menu pages
- one rendered background image per page
- rectangular button hitboxes
- geometry-derived focus order / neighbor navigation
- simple play-title actions mapped to playlists/title numbers
- simple go-to-menu/page actions
- return-to-main-menu actions as navigation back to the first menu page
- no BD-J/JAR/BDJO payloads

BD-J-required in the current implementation:

- looping/motion/windowed menu video
- Java media control behavior beyond the static HDMV-Lite subset
- button graphics layered over transparent video windows
- any custom action not representable as play-title, go-to-menu, or return-main-menu

### Tradeoffs

- **HDMV** should eventually be more compatible with standalone players because it avoids Java startup, BD-J signing, and player-specific Java behavior. The tradeoff is that the open-source implementation is still incomplete and must stay within a conservative static-menu subset first.
- **BD-J/GRIN** is the proven path in this project today and supports the existing PowerPoint workflow, motion/menu-loop behavior, Java playback control, and return-to-menu behavior. The tradeoff is higher complexity and more variation across players.

Validate the generated GRIN/BD-J menu:

```bash
cd xlets/grin_samples/Scripts/PptxMenu
ant default
```

## Button and video matching

A normal text box/button whose visible text matches a video filename stem becomes a selectable video action.

Examples:

```text
PowerPoint text: Main Feature
Video file:      Main Feature.mkv
```

Safe relaxed matching handles punctuation and common release metadata when unambiguous:

```text
PowerPoint text: Just Friends
Video file:      Just.Friends.2005.720p.mp4
```

The converter writes informational warnings for relaxed/fuzzy matches so the TUI can surface them during preflight.

## Slide navigation

PowerPoint hyperlinks to other slides become GRIN segment transitions. Generated slide entry segments use this pattern:

```text
S:slide1.Enter -> S:slide1
S:slide2.Enter -> S:slide2
```

The `.Enter` segment gives the generated Java hook a clean place to start/stop autoplay menu loops before the interactive slide segment becomes active.

## Autoplay looped slide video

Autoplay loops are intended for motion menus. Use a shape/text box where the video should appear and name it like a matching video file. Names containing words such as `Background`, `Preview`, `Loop`, or `Autoplay` are treated as loop placeholders instead of clickable video buttons.

Example project:

```text
menu.pptx
Just.Friends.2005.720p.mp4
background 1.mp4
background 2.mp4
background 3.mp4
```

PowerPoint shapes:

```text
Background 1   -> background 1.mp4
Background 2   -> background 2.mp4
Background 3   -> background 3.mp4
Just Friends   -> Just.Friends.2005.720p.mp4 clickable movie button
```

Implementation notes:

- The converter renders each PowerPoint slide to a PNG.
- Loop placeholder regions are cut out of the graphics layer so video can show through.
- Each slide's loop regions are composited into a generated 30-second source clip under `build/pptx-menu-loops/`.
- Generated loop clips are encoded with the rest of the project and assigned playlist IDs with `kind: loop`.
- BD-J starts the slide's loop playlist when entering the slide.
- End-of-media restarts the loop playlist.
- Buttons that overlap loop regions get normal-state crop overlays (`*_normal.png`) above the video layer, so motion video stays behind menu controls.

`source-videos.json` records raw loop source clips so media analysis does not encode them as standalone titles:

```text
build/pptx-menu-loops/source-videos.json
```

## Media encoding and disc targets

Encode manually:

```bash
./scripts/prepare-bluray-media.sh "/path/to/project"
```

Disc presets:

```text
dvd5     DVD-5-sized Blu-ray/AVCHD target, 192k AC-3
dvd9     DVD-9-sized Blu-ray/AVCHD target, 256k AC-3
bd25     single-layer Blu-ray target, 448k AC-3
quality  CRF/CQ quality mode with no size cap
```

Examples:

```bash
./scripts/prepare-bluray-media.sh "/path/to/project" --disc-preset bd25
./scripts/prepare-bluray-media.sh "/path/to/project" --disc-preset dvd9
./scripts/prepare-bluray-media.sh "/path/to/project" --only "Main Feature" --smoke-seconds 30
```

The workflow skips existing encodes only when they match the current options and probe as acceptable. Partial, stale, oversized, or mismatched outputs are flagged in the TUI.

## Subtitles

Sidecar subtitle files are associated by filename prefix:

```text
Main Feature.mkv
Main Feature.srt
Main Feature Spanish.srt
```

If no sidecar is found, autopilot can try OpenSubtitles before media analysis:

```bash
export OPENSUBTITLES_API_KEY='your-api-key'
export OPENSUBTITLES_USERNAME='your-username'
export OPENSUBTITLES_PASSWORD='your-password'
export OPENSUBTITLES_LANGUAGE='en'   # optional
```

Missing credentials are informational, not fatal.

## Authoring handoff

Generate mux/playlist plan:

```bash
./scripts/create-bluray-authoring-plan.sh "/path/to/project"
```

Outputs:

```text
build/bluray-authoring/playlist-map.json
build/bluray-authoring/mux-plan.md
build/bluray-authoring/tsmuxer-meta/*.meta
```

The authoring plan deduplicates repeated playlist IDs, so the same movie button reused on multiple slides maps to one title, while generated loop clips get their own loop playlist entries.

## Final ISO

Build final ISO manually:

```bash
./scripts/create-final-bluray-iso.sh "/path/to/project" --volume-id "MY_DISC" --disc-preset bd25 --menu-backend bdj
```

Outputs:

```text
build/final-bluray/disc-root/
build/final-bluray/bluray-project.iso
build/final-bluray/final-report.json
```

The final ISO builder validates:

- encoded files exist and are full-length
- video is H.264
- audio is 48 kHz AC-3
- selected disc target is not exceeded unless `--allow-oversized`
- generated PPTX slide assets referenced by the menu JAR are present
- playlist map matches available encoded assets

## Burning

Autopilot checks `/dev/sr*` devices with xorriso. If a blank/appendable/overwriteable disc has enough capacity, it burns automatically.

Manual burn from TUI:

```text
v  choose burner
b  burn final ISO
```

Burn logs/state:

```text
build/bluray-burn/
```

## Troubleshooting checklist

- Run the TUI and read preflight diagnostics before starting autopilot.
- Confirm `menu.pptx` exists and LibreOffice can open/export it.
- Check `video-actions.json` for button and loop mappings.
- Check `build/bluray-media/media-manifest.json` for the actual encode list.
- Raw loop source clips should appear in `source-videos.json`, not as standalone titles in the manifest.
- If buttons disappear over motion video, ensure the converter generated `*_normal.png` overlays for buttons intersecting loop regions.
- If GRIN fails to compile, run `cd xlets/grin_samples/Scripts/PptxMenu && ant default` and inspect the parser error line in `pptx-menu.txt`.
- If final ISO fails, inspect `build/final-bluray/final-report.json` and the latest `build/bluray-workflow/autopilot.log`.

## Upstream HD Cook Book notes

HD Cook Book is old BD-J code. It is happiest with:

- JDK 8
- Apache Ant
- BD-J platform stubs

The archived repository already contains BD-J stub classes at:

```text
lib/stubs/enhanced/classes.zip
```

`user.vars.properties.example` points the build at those stubs. The build script copies it to `user.vars.properties` automatically when needed.
