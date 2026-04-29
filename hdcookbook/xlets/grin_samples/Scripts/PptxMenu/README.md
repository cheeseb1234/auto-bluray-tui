# PptxMenu — generated from menu.pptx

Generated from:

```text
/home/corey/.openclaw/Bluray project/menu.pptx
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
    "button": "Video 1",
    "action": {
      "kind": "video",
      "target": "Video 1.mkv",
      "video_file": "Video 1.mkv",
      "playlist_id": "00001",
      "title_number": 1,
      "encoded_m2ts": "build/bluray-media/encoded/Video 1.m2ts"
    }
  },
  {
    "slide": "slide2",
    "button": "Video 2",
    "action": {
      "kind": "video",
      "target": "Video 2.mp4",
      "video_file": "Video 2.mp4",
      "playlist_id": "00002",
      "title_number": 2,
      "encoded_m2ts": "build/bluray-media/encoded/Video 2.m2ts"
    }
  },
  {
    "slide": "slide3",
    "button": "Video 3",
    "action": {
      "kind": "video",
      "target": "Video 3.mkv",
      "video_file": "Video 3.mkv",
      "playlist_id": "00003",
      "title_number": 3,
      "encoded_m2ts": "build/bluray-media/encoded/Video 3.m2ts"
    }
  },
  {
    "slide": "slide3",
    "button": "Video 4",
    "action": {
      "kind": "video",
      "target": "Video 4.mp4",
      "video_file": "Video 4.mp4",
      "playlist_id": "00004",
      "title_number": 4,
      "encoded_m2ts": "build/bluray-media/encoded/Video 4.m2ts"
    }
  }
]

These preview as button activation feedback and call a generated `playVideo(videoFile, playlistId)` hook that starts the matching Blu-ray playlist.
