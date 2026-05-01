# PptxMenu — generated from project PPTX

Generated from:

```text
/tmp/bluray-project-preview.nBnfrt/menu.pptx
```

Edit the PowerPoint, then rerun:

```bash
./scripts/convert-pptx-menu.sh "/home/corey/.openclaw/Bluray project"
```

Preview:

```bash
cd xlets/grin_samples/Scripts/PptxMenu
ant preview
```

## Detected video actions

[
  {
    "slide": "slide2",
    "button": "a",
    "action": {
      "kind": "video",
      "target": "a.mp4",
      "video_file": "a.mp4",
      "playlist_id": "00001",
      "title_number": 1,
      "encoded_m2ts": "build/bluray-media/encoded/a.m2ts",
      "type": "play_title",
      "video_target": "a.mp4",
      "playlist": "00001"
    }
  },
  {
    "slide": "slide2",
    "button": "b",
    "action": {
      "kind": "video",
      "target": "b.mp4",
      "video_file": "b.mp4",
      "playlist_id": "00002",
      "title_number": 2,
      "encoded_m2ts": "build/bluray-media/encoded/b.m2ts",
      "type": "play_title",
      "video_target": "b.mp4",
      "playlist": "00002"
    }
  }
]

These preview as button activation feedback and call a generated `playVideo(videoFile, playlistId)` hook that starts the matching Blu-ray playlist.
