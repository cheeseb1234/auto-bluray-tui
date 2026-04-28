# Auto Blu-ray TUI Walkthrough

This walkthrough shows a typical Auto Blu-ray TUI project from source files to final ISO/burned disc.

The screenshots below are mockups, but they match the intended workflow and naming rules.

## 1. Create your project folder

Put your PowerPoint menu, videos, and optional subtitles in one folder.

![Mock project folder](assets/mock-project-folder.svg)

Example:

```text
My Blu-ray Project/
├── menu.pptx
├── Video 1.mkv
├── Video 1.srt
├── Video 2.mp4
├── Video 2.srt
├── Video 3.mkv
├── Video 3.srt
├── Video 4.mp4
├── Video 4.srt
└── Video 4 Spanish.srt
```

Auto Blu-ray TUI writes generated files into `build/` inside this same project folder. Your original media files are not moved.

## 2. Name PowerPoint buttons to match video files

The important rule is simple:

> A PowerPoint button becomes a video button when its visible text exactly matches a video filename **without the extension**, case-insensitively.

Examples:

| PowerPoint button text | Matches video file | Notes |
| --- | --- | --- |
| `Video 1` | `Video 1.mkv` | Good |
| `Video 2` | `Video 2.mp4` | Good |
| `Feature Film` | `Feature Film.mkv` | Good |
| `Play Feature Film` | `Feature Film.mkv` | Does **not** match unless the file is named `Play Feature Film.mkv` |
| `Video 4` | `Video 4.mp4` | Sidecars like `Video 4 Spanish.srt` are still associated later |

The converter scans video files with these extensions:

```text
.mkv .mp4 .m2ts .mov
```

It compares each PowerPoint text box/button against the video file stem:

```text
Video 1.mkv → stem is "Video 1"
```

So a PowerPoint text box labeled `Video 1` maps to `Video 1.mkv`.

![Mock PowerPoint menu](assets/mock-pptx-menu.svg)

### Slide navigation buttons

PowerPoint hyperlinks to other slides are preserved as menu navigation buttons. For example, a `Next` button linked to slide 2 stays a menu navigation button.

### Video buttons

Text boxes whose labels match video file stems become video actions. During conversion, the project writes:

```text
xlets/grin_samples/Scripts/PptxMenu/video-actions.json
```

Example generated mapping:

```json
[
  {
    "slide": "slide2",
    "button": "Video 1",
    "video_file": "Video 1.mkv",
    "playlist_id": "00001",
    "title_number": 1,
    "encoded_m2ts": "build/bluray-media/encoded/Video 1.m2ts"
  }
]
```

Playlist IDs are assigned in first-seen order:

```text
Video 1 → 00001
Video 2 → 00002
Video 3 → 00003
Video 4 → 00004
```

If the same video appears on multiple slides, it reuses the same playlist ID.

## 3. Install dependencies

From the repository’s `hdcookbook/` directory:

```bash
./scripts/install-bluray-deps.sh
```

Check-only mode:

```bash
./scripts/install-bluray-deps.sh --check-only
```

The installer checks common dependencies such as ffmpeg, LibreOffice, Poppler, Ant/Java, xorriso, and tsMuxer.

## 4. Launch the TUI

```bash
./scripts/monitor-bluray-project.sh "/path/to/My Blu-ray Project"
```

Example:

```bash
./scripts/monitor-bluray-project.sh "/home/corey/.openclaw/Bluray project"
```

Main controls:

```text
w      start full autopilot
Enter  encode only
b      burn final ISO
v      cycle detected optical burner
k      stop running encode/autopilot/burn
q      quit
```

## 5. Start autopilot

Press `w`.

The TUI works through these steps:

1. analyze project/media
2. process `menu.pptx`
3. check/install tsMuxer
4. encode Blu-ray media
5. create authoring plan
6. build BD-J menu overlay
7. assemble final ISO
8. auto-burn first disc if a suitable blank disc is detected

![Mock TUI autopilot](assets/mock-tui-autopilot.svg)

## 6. Encoding and BD-25 sizing

For BD-25 output, the TUI defaults to:

```text
disc=bd25
encoder=auto
```

`encoder=auto` uses NVIDIA NVENC when available and falls back to CPU otherwise.

The workflow rejects existing encodes that are too large for BD-25. Good existing encodes are skipped, so reruns do not waste time.

## 7. Final outputs

When successful, the project folder contains:

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

## 8. Burn the disc

If a blank disc is inserted and large enough, autopilot burns the first disc automatically.

You can also burn manually from the TUI:

1. insert a blank BD-R/BD-RE
2. press `v` if you need to choose a different burner
3. press `b` to burn
4. when it ejects, insert another blank disc and press `b` again, or press `q` to exit

![Mock burn ready screen](assets/mock-burn-ready.svg)

## Troubleshooting naming problems

If a PowerPoint video button does not work, check these first:

- Does the button text exactly match the video filename stem?
- Is the video file in the same project folder as `menu.pptx`?
- Is the video extension one of `.mkv`, `.mp4`, `.m2ts`, or `.mov`?
- Did LibreOffice successfully convert the PowerPoint?
- Check generated `video-actions.json` to confirm the mapping.

Good:

```text
Button text: Feature 1
Video file:  Feature 1.mkv
```

Bad:

```text
Button text: Play Feature 1
Video file:  Feature 1.mkv
```

Fix either by changing the button text to `Feature 1` or renaming the file to `Play Feature 1.mkv`.
