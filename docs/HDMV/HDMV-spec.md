# HDMV implementation scratchpad

Distilled from `HDMV deep-research-report.md` after pushing the backend scaffold.

## Core file graph

A pure HDMV menu path should eventually emit/use:

```text
BDMV/index.bdmv              # First Playback / Top Menu / title dispatch
BDMV/MovieObject.bdmv        # HDMV navigation-command programs
BDMV/PLAYLIST/*.mpls         # playlists/playitems/subpaths
BDMV/CLIPINF/*.clpi          # clip metadata aligned with STREAM
BDMV/STREAM/*.m2ts           # video/audio plus eventual IG/PG/TextST streams
BDMV/AUXDATA/sound.bdmv      # optional button sounds
BDMV/AUXDATA/*.otf           # only for TextST, not v0 HDMV-Lite
BDMV/BACKUP/*                # mirrors index, MovieObject, PLAYLIST, CLIPINF
CERTIFICATE/                 # structural compatibility folder
```

Pure HDMV should omit `BDMV/BDJO/` and `BDMV/JAR/`; needing those means the BD-J backend is in use.

## Dispatch model

- `index.bdmv` is the top-level dispatcher.
- First Playback is special title `0xFFFF`.
- Top Menu is special title `0`.
- Each index entry has an object type: HDMV -> Movie Object ID, BD-J -> BDJO target.
- HDMV First Playback and Top Menu should both point to Movie Objects.

## MovieObject model

Conceptual public model:

```text
MovieObject.bdmv
  object[n]
    resume_intention_flag
    menu_call_mask
    title_search_mask
    command[0..n]
```

Useful public command vocabulary from tools/docs:

- `Nop`
- `GoTo`
- `JumpObject`
- `JumpTitle`
- `CallObject`
- playlist launch/playback commands
- page/button display controls such as `SetButtonPage`

The exact binary encoding/opcode surface is the weak public-doc area; libbluray devtools and BDedit are validation oracles.

## Interactive Graphics model

HDMV IG authoring should model:

- interactive composition / display set
- pages, IDs `0x00..0xFE`
- BOGs: Button Overlap Groups; one non-disabled button per BOG
- buttons:
  - unique within page
  - numeric select value
  - auto-action flag
  - x/y coordinates
  - upper/lower/left/right neighbor refs
  - normal/selected/activated object refs
  - optional selected/activated sound refs to `sound.bdmv`
- palettes and bitmap objects:
  - 8-bit indexed color
  - 24-bit color + 8-bit alpha
  - object chains for simple state animation later

Important invariant: state object chains must reference existing objects with matching dimensions.

## Practical HDMV-Lite v0 target

Goal: prove complete HDMV-only static menu navigation, not full HDMV.

Accept initially:

- standard 1080p Blu-ray BDMV only
- static top menu / simple static pages
- rectangular hitboxes from neutral model
- geometry-derived remote-neighbor navigation
- play-title action -> playlist/title
- go-to-menu/page action
- return/main-menu object flow if it can be expressed cleanly in MovieObject commands
- no BDJO/JAR/Java payloads

Reject/fall back to BD-J initially:

- motion/windowed menu video
- complex animation/timeline effects
- app/game/quiz logic
- Java/Xlet behavior
- rich persistent state
- TextST authoring as a baseline feature
- UHD/HDR/Dolby Vision menu compliance

## Validation targets

Use software validation, then real hardware/BD-RE validation.

Public tool anchors:

```bash
index_dump <disc_root>
mobj_dump -d BDMV/MovieObject.bdmv
mpls_dump -i -c -p BDMV/PLAYLIST/00000.mpls
clpi_dump -c -p -i BDMV/CLIPINF/00000.clpi
hdmv_test [-v] [-t <title>] <media_path> [<keyfile_path>]
sound_dump BDMV/AUXDATA/sound.bdmv
```

BDedit and DVDLogic IG Editor are useful external oracle/reference tools, not UX dependencies.

## Implementation direction

1. Keep current neutral PowerPoint menu model as frontend IR.
2. Add a second, lower-level HDMV IR:
   - index entries
   - movie objects/commands
   - playlists/playitems/clip refs
   - IG display set/pages/BOGs/buttons/objects/palettes/sounds
3. First backend milestone can emit a human-reviewable HDMV export package before compiling binaries.
4. Later compiler writes `index.bdmv`, `MovieObject.bdmv`, IG stream/assets, and updates playlists/clip info coherently.
5. Add validation commands and real-player compatibility matrix before making HDMV the true working default.

## Current caution

The research report has useful technical content, but the checked-in markdown includes embedded prompt/chat fragments in the middle of the file. Clean it before treating it as polished project documentation.
