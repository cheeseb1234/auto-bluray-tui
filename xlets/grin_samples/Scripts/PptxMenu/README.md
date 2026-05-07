# PptxMenu — generated from project PPTX

Generated from:

```text
/mnt/llm/example/menu.pptx
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
    "slide": "slide1",
    "button": "Jello",
    "action": {
      "kind": "video",
      "type": "play_title",
      "target": "jello.mp4",
      "video_file": "jello.mp4",
      "playlist_id": "00001",
      "title_number": 1,
      "encoded_m2ts": "build/bluray-media/encoded/jello.m2ts",
      "video_target": "jello.mp4",
      "playlist": "00001"
    }
  },
  {
    "slide": "slide1",
    "button": "Butter",
    "action": {
      "kind": "video",
      "type": "play_title",
      "target": "butter.mp4",
      "video_file": "butter.mp4",
      "playlist_id": "00002",
      "title_number": 2,
      "encoded_m2ts": "build/bluray-media/encoded/butter.m2ts",
      "video_target": "butter.mp4",
      "playlist": "00002"
    }
  },
  {
    "slide": "slide2",
    "button": "Gravy",
    "action": {
      "kind": "video",
      "type": "play_title",
      "target": "gravy.mp4",
      "video_file": "gravy.mp4",
      "playlist_id": "00003",
      "title_number": 3,
      "encoded_m2ts": "build/bluray-media/encoded/gravy.m2ts",
      "video_target": "gravy.mp4",
      "playlist": "00003"
    }
  },
  {
    "slide": "slide2",
    "button": "Cheese",
    "action": {
      "kind": "video",
      "type": "play_title",
      "target": "cheese.mp4",
      "video_file": "cheese.mp4",
      "playlist_id": "00004",
      "title_number": 4,
      "encoded_m2ts": "build/bluray-media/encoded/cheese.m2ts",
      "video_target": "cheese.mp4",
      "playlist": "00004"
    }
  }
]

These preview as button activation feedback and call a generated `playVideo(videoFile, playlistId)` hook that starts the matching Blu-ray playlist.
