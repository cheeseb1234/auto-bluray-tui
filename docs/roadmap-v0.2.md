# Auto Blu-ray TUI v0.2 roadmap

## Status

`docs/merged-codex-work-plan.md` is now the detailed execution plan for the project.

Use this file as the short public roadmap and decision summary. Use the merged plan for phase-by-phase implementation order, acceptance criteria, and Codex prompts.

## Product stance

Auto Blu-ray TUI should optimize for a **reliable, practical Blu-ray authoring workflow**.

Given:

- one project folder
- one PowerPoint menu
- one or more videos

Auto Blu-ray TUI should reliably:

1. analyze the project
2. convert the menu
3. encode compliant media
4. author a disc layout
5. build a final ISO
6. optionally burn it

The shipping backend remains **BD-J / GRIN**.

HDMV remains **experimental** until a functional static-menu compiler path is proven on real playback targets.

## Strategic decisions

### Keep and strengthen

- PowerPoint-first authoring workflow
- backend-neutral `menu-model.json`
- BD-J / GRIN as the shipping backend
- menu compatibility reporting for future HDMV work
- packaged app workflow
- `--doctor` diagnostics
- resumable / visible TUI behavior

### Freeze for now

Keep HDMV as research/export/scaffold work:

- keep HDMV IR/package export
- keep HDMV compatibility analysis
- keep HDMV validation notes/runbooks
- keep HDMV-Lite scaffolding

Do not yet:

- default to HDMV
- claim Java-free menus are production-ready
- chase HDMV parity before the core BD-J workflow is stable

### Avoid for now

- UHD Blu-ray scope
- major menu DSL expansion before stability
- platform dependency mysteries hidden from the user
- giant rewrites that make the existing BD-J path regress

## Master priority order

1. **P0 — Release/runtime reliability**
   - packaged app works without Python hand-fixing
   - actionable dependency diagnostics
   - early TUI preflight warnings
   - packaged smoke tests
2. **P1 — Known-good authoring path**
   - demo project / known-good fixtures
   - CI smoke build path
   - clearer failure messages
3. **P2 — Existing media tools first**
   - make `ffprobe`, `ffmpeg`, `tsMuxer`, ISO tools, and playback validators the bounded engines
   - add structured wrappers, reports, planning, validation, and tests before deeper workflow rewrites
4. **P3 — Architecture cleanup**
   - move toward a real Python package under `src/auto_bluray_tui`
   - split the giant monitor/workflow code without regressing behavior
5. **P4 — User-facing disc quality**
   - better navigation, setup menus, reports, and player compatibility notes
6. **P5 — HDMV Gate 1**
   - only after the stable BD-J path is solid

## Near-term execution phases

The detailed plan lives in `docs/merged-codex-work-plan.md`. The immediate sequence is:

1. **Phase 1 — CI and Release Safety**
   - add normal GitHub Actions CI for tests
   - make release workflow depend on passing tests
   - add lint/tooling baseline
2. **Phase 2 — Public Polish and Versioning**
   - remove personal/local paths
   - centralize versioning
3. **Phase 3 — Dependency Diagnostics and Platform Hardening**
   - unify dependency checks
   - classify dependencies by workflow stage
   - make tsMuxer detection architecture-aware
4. **Phase 4 — P0 Packaged Runtime Reliability**
   - ensure helper scripts use packaged Python
   - improve `--doctor`
   - add early TUI preflight warnings
5. **Phase 5 — Known-Good Authoring Path**
   - add demo project generator
   - add smoke build coverage
   - add known-good report expectations
6. **Phase 5B — Existing Media Tools First**
   - add ffprobe media model
   - add compatibility reports
   - add copy/remux/transcode planning
   - centralize FFmpeg/tsMuxer wrappers and validation

## HDMV Gate 1

HDMV should only move back into active development after the stable BD-J path is strong.

The first real HDMV milestone is one static playable menu disc that can:

- open main menu
- choose between two titles
- jump to a title
- return to main menu

Validation target:

- libbluray tooling
- at least one real standalone player

Until that works, BD-J remains the shipping backend and HDMV stays gated.

## Definition of done

The merged plan is successful when:

- release artifacts still build
- normal CI runs unit tests on Linux, macOS, and Windows
- release artifacts are not published if tests fail
- `auto-bluray-tui --doctor` works on target platforms
- public docs/scripts contain no personal paths
- versioning is centralized
- core Python modules migrate under `src/auto_bluray_tui`
- media metadata/planning/validation are structured and tested
- workflow orchestration is mostly Python instead of generated Bash
- TUI behavior remains intact
- BD-J stays the shipping backend
- HDMV stays gated until static playback is proven
