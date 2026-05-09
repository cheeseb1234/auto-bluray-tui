# Auto Blu-ray TUI Merged Codex Work Plan

## Purpose

This plan merges the existing GitHub planning docs with the refactor/hardening plan.

Merged inputs:

- `docs/roadmap-v0.2.md`
- `docs/auto tui possible upgrades.md`
- `docs/HDMV/HDMV plan.md`
- new architecture/refactor recommendations from the repository review

The guiding idea is:

> Stabilize the current BD-J/GRIN shipping path first. Keep HDMV as research/export/scaffold work until a real static HDMV menu can be proven. Refactor only in ways that make the existing workflow more reliable and easier to maintain.

---

## Product Stance

Auto Blu-ray TUI should optimize for a reliable, practical Blu-ray authoring workflow.

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

The working backend remains **BD-J / GRIN**.

HDMV remains **experimental** until a functional compiler path exists.

---

## Strategic Decisions

### Keep and strengthen

- PowerPoint-first authoring workflow
- backend-neutral `menu-model.json`
- BD-J / GRIN as the shipping backend
- menu compatibility reporting for future HDMV work
- packaged app workflow
- `--doctor` diagnostics
- resumable / visible TUI behavior

### Freeze for now

HDMV should not be marketed as a working final menu path yet.

Keep:

- HDMV IR/package export
- HDMV compatibility analysis
- HDMV validation notes/runbooks
- HDMV-Lite scaffolding

Do not yet:

- default to HDMV
- claim Java-free menus are production-ready
- chase HDMV parity before the core BD-J workflow is stable

### Avoid for now

- UHD Blu-ray scope
- major menu DSL expansion before stability
- platform dependency mysteries hidden from the user
- giant rewrites that make the existing BD-J path regress

---

# Master Priority Order

## P0 — Release/runtime reliability

This is the highest priority. A user should be able to run the packaged app, understand missing dependencies, and build a BD-J-backed ISO without manually debugging Python, Java, shell scripts, or hidden helper runtimes.

## P1 — Known-good authoring path

Once packaging is stable, create a repeatable demo/smoke build path that proves the workflow end-to-end.

## P2 — Existing media tools first

Use ffprobe, ffmpeg, tsMuxer, xorriso/mkisofs, and libbluray/VLC more deliberately before building custom media logic. Add structured wrappers, reports, planning, validation, and tests around those tools.

## P3 — Architecture cleanup

Refactor the codebase into a maintainable Python application while preserving current behavior.

## P4 — User-facing disc quality

Improve menu navigation, setup menus, reports, and testing across real players.

## P5 — HDMV Gate 1

Only after the stable BD-J path is strong, prove one minimal static HDMV menu disc.

---

# Phase 1 — CI and Release Safety

## 1. Add normal CI for unit tests

Create `.github/workflows/ci.yml`.

Run on:

```yaml
on:
  push:
  pull_request:
```

Test matrix:

```yaml
os: [ubuntu-latest, macos-latest, windows-latest]
python: ["3.10", "3.11", "3.12"]
```

Core commands:

```bash
python -m pip install --upgrade pip
python -m pip install -e .
python -m unittest discover -s tests
```

Acceptance criteria:

- CI runs on push and pull request.
- Unit tests run on Linux, macOS, and Windows.
- Unit tests do not require real ffmpeg, Java, tsMuxer, LibreOffice, or burner hardware.
- Failing tests block pull requests.

## 2. Make release workflow depend on tests

Update `.github/workflows/release.yml`.

Accept either:

- a separate `test` job with `needs: test`, or
- test steps before PyInstaller packaging in each matrix job.

Acceptance criteria:

- Tagged releases cannot upload artifacts if tests fail.
- Existing PyInstaller smoke tests remain.
- Existing `--help`, `--doctor`, and packaged helper runtime smoke tests remain.

## 3. Add lint/tooling baseline

Add dev dependencies:

```toml
[project.optional-dependencies]
dev = [
  "ruff>=0.5",
]
```

Add Ruff config:

```toml
[tool.ruff]
target-version = "py310"
line-length = 100
extend-exclude = [
  "AuthoringTools",
  "DiscCreationTools",
  "xlets",
  "bin",
]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
ignore = []
```

Acceptance criteria:

- `python -m ruff check start.py install.py tools tests` runs in CI.
- Legacy/vendor directories are excluded.
- Ruff cleanup is committed separately from behavior changes where possible.

---

# Phase 2 — Public Polish and Versioning

## 4. Remove personal/local paths

Remove public references such as:

```text
/home/corey/.openclaw/Bluray project
```

Replace with:

```text
/path/to/Blu-ray project
```

or require explicit project arguments.

Update:

- `scripts/monitor-bluray-project.sh`
- `scripts/install-bluray-deps.sh`
- README examples if present
- release README if present
- tests that assert old examples

Recommended wrapper behavior:

```bash
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 /path/to/project" >&2
  exit 2
fi
```

Acceptance criteria:

- No personal paths appear in public scripts/docs.
- Wrapper scripts fail clearly if project path is missing.

## 5. Centralize versioning

Prevent package version and GitHub release version from drifting.

Preferred:

- use `setuptools_scm` and derive version from tags.

Alternative:

- add `src/auto_bluray_tui/_version.py`
- import from there in package metadata and diagnostics.

Acceptance criteria:

- `auto-bluray-tui --doctor` prints app/package version.
- Release artifact version matches Git tag.
- Version does not require duplicate manual edits.

---

# Phase 3 — Dependency Diagnostics and Platform Hardening

## 6. Unify dependency checks

Create one shared dependency module that owns:

- Java detection
- Apple `/usr/bin/java` stub detection
- ffmpeg detection
- ffprobe detection
- tsMuxer detection
- xorriso / mkisofs / genisoimage detection
- LibreOffice detection
- pdftoppm/poppler detection
- Ant detection
- platform-specific remediation hints

Likely future module:

```text
src/auto_bluray_tui/dependencies.py
```

Acceptance criteria:

- `--doctor` uses the shared module.
- TUI preflight uses the shared module.
- installer messages match doctor messages.
- dependency checks are unit tested with mocked PATH/platform/subprocess results.

## 7. Classify dependencies by workflow stage

Not every missing dependency should prevent opening the TUI.

Suggested classification:

| Stage | Required tools |
|---|---|
| Launch TUI | Python, curses/windows-curses |
| Analyze media | ffprobe |
| Encode media | ffmpeg |
| Convert PPTX | LibreOffice, pdftoppm/poppler |
| BD-J build | Java, Ant, HD Cook Book assets |
| Final mux/ISO | tsMuxer, UDF-capable ISO creator |
| Burn | platform-specific burner tools |

Acceptance criteria:

- Missing final-stage tools show warnings until needed.
- Launching the TUI does not fail because tsMuxer or xorriso is missing.
- Autopilot blocks early with clear messages if the selected workflow needs missing tools.

## 8. Make tsMuxer detection platform/architecture-aware

The app should detect:

- missing binary
- non-executable binary
- Linux binary accidentally used on macOS
- wrong CPU architecture
- macOS `bad CPU type in executable`
- Apple Silicon binary on Intel Mac
- Intel binary on Apple Silicon without Rosetta, if applicable

Example message:

```text
tsMuxer was found but cannot run on this machine.

Found: /usr/local/bin/tsMuxer
Problem: bad CPU type in executable
This usually means the binary was built for a different Mac architecture.

Install a macOS x86_64 tsMuxer build for this Intel Mac, or remove the incompatible binary from PATH.
```

Acceptance criteria:

- macOS Intel wrong-arch tsMuxer produces a clear remediation message.
- macOS Apple Silicon wrong-arch tsMuxer produces a clear remediation message or Rosetta hint.
- `--doctor` reports tsMuxer path, status, and architecture problem when known.
- The app does not crash during optional dependency checks.

## 9. Stop Linux-only tsMuxer downloads on non-Linux platforms

Current auto-download logic must not download Linux tsMuxer on macOS or Windows.

Acceptance criteria:

- Linux can still auto-download a Linux tsMuxer build.
- macOS prints instructions instead of downloading Linux binaries.
- Windows prints instructions or uses a tested Windows-specific download.
- release docs match actual behavior.

---

# Phase 4 — P0 Packaged Runtime Reliability

## 10. Packaged app works without Python hand-fixing

Ensure helper shell scripts use the packaged Python runtime when launched from PyInstaller builds.

Acceptance criteria:

- bundled dependencies such as `requests` are available end-to-end
- `fetch-opensubtitles.sh` does not accidentally use system Python when the packaged runtime should be used
- packaged smoke tests catch `ModuleNotFoundError`

## 11. Improve `--doctor`

`--doctor` should report:

- OS
- architecture
- app version
- package/bundle mode
- Python runtime
- Java status
- ffmpeg/ffprobe status
- tsMuxer status and architecture problem if known
- ISO creator status
- LibreOffice/poppler status
- Ant status
- OpenSubtitles helper dependency status
- exact remediation commands where practical

Acceptance criteria:

- A macOS or Linux user can run `--doctor` and understand what to install.
- It distinguishes “missing” from “found but broken.”
- It detects Apple's Java stub correctly.
- It does not fail just because an optional tool is missing.

## 12. Early TUI preflight warnings

Before starting expensive work, warn for:

- missing tsMuxer
- missing UDF ISO tool
- missing xorriso/burn support
- missing requests when OpenSubtitles is enabled
- missing or ambiguous PPTX
- no videos
- menu buttons not matching videos
- stale final ISO

Acceptance criteria:

- Warnings appear before autopilot begins.
- Blocking issues are clearly separated from non-blocking warnings.
- Remediation text is short and actionable.

---

# Phase 5 — Known-Good Authoring Path

## 13. Create a tiny demo project generator

Add a command or script that creates a small synthetic project:

```bash
auto-bluray-tui demo-project /tmp/bluray-demo
```

or:

```bash
python -m auto_bluray_tui demo-project /tmp/bluray-demo
```

The demo should include:

- one simple generated PowerPoint or fixture menu
- one or two tiny generated videos
- optional subtitles

Use generated/free assets only.

Acceptance criteria:

- Demo project is legal and tiny.
- It works on CI where possible.
- It gives contributors a known baseline.

## 14. Add demo smoke build in CI where practical

Smoke build stages:

- project analysis
- menu conversion
- media analysis
- authoring plan generation
- BD-J menu build if dependencies are available or mocked
- final report validation

Acceptance criteria:

- CI can prove the known-good path without optical burner hardware.
- If full ISO creation is too heavy for all platforms, run it on Linux only first.
- Smoke failures point to exact failing stage.

## 15. Create known-good final report expectations

For the demo project, assert:

- title count
- playlist map shape
- menu model shape
- final report keys
- expected backend is BD-J

Acceptance criteria:

- regressions in menu/action mapping are caught early.
- final report remains stable enough for troubleshooting.

---

# Phase 5B — Leverage Existing Media Tools First

This phase should happen before deeper workflow rewrites. The goal is to reduce custom media logic by treating mature command-line tools as bounded engines with clear inputs, outputs, and validation.

## Tool ownership model

Use each tool for what it is best at:

| Tool | Primary role |
|---|---|
| `ffprobe` | media metadata, stream/chapter inspection, compatibility reporting |
| `ffmpeg` | normalization, encode/remux/copy decisions, thumbnails, previews, progress |
| `tsMuxer` | Blu-ray/M2TS muxing, track metadata, subtitle handling where supported |
| `xorriso` / `mkisofs` / `genisoimage` | UDF ISO creation |
| `libbluray` / VLC | playback/navigation smoke validation where practical |
| Java / Ant / GRIN | BD-J menu build until HDMV is proven functional |

Do not make FFmpeg responsible for Blu-ray menu authoring. Let FFmpeg own media preparation and validation. Let tsMuxer own Blu-ray muxing. Let BD-J/GRIN or future HDMV code own menus.

## 16A. Create an ffprobe media model

Add a Python module that wraps `ffprobe` JSON output into typed/structured data.

Suggested module:

```text
src/auto_bluray_tui/media/probe.py
```

It should expose functions/classes for:

- container format
- duration
- file size
- bitrate
- video streams
- audio streams
- subtitle streams
- chapters
- frame rate
- resolution
- pixel format
- color range / HDR metadata when present
- sample rate
- channel layout
- language tags
- timecode when present

Acceptance criteria:

- ffprobe command construction is centralized.
- JSON parsing is tested with fixture JSON, not real media files.
- ffprobe errors produce clear messages.
- existing media analysis behavior is preserved.

## 16B. Add a media compatibility report

Use the ffprobe media model to produce a preflight report for every input video.

Report examples:

```text
Main Feature.mkv
Status: needs encode
Reasons:
- video codec is HEVC; current Blu-ray target expects H.264
- audio is AAC 44.1 kHz; target expects AC-3 48 kHz
- source has 12 chapters available for future scene menu generation
```

Acceptance criteria:

- TUI can display short compatibility status per title.
- Full JSON/Markdown report is written under `build/bluray-media/`.
- Report distinguishes:
  - already compliant
  - remux/copy possible
  - audio-only transcode needed
  - video transcode needed
  - unsupported/missing streams
- No output behavior changes yet unless explicitly requested.

## 16C. Add copy/remux/transcode planning

Create a planning layer that decides the least destructive operation needed per stream.

Suggested module:

```text
src/auto_bluray_tui/media/plan.py
```

The planner should decide:

- copy video if already compliant
- copy audio if already compliant
- transcode audio only if video is compliant but audio is not
- remux when container is the only issue
- full transcode only when necessary
- force transcode when user requests a disc-size target or lower resolution

Acceptance criteria:

- Planner emits a structured plan before running FFmpeg.
- Existing “encode everything to H.264 + AC-3” behavior can remain the default until confidence is high.
- New smarter behavior is introduced behind an option such as `--smart-copy` or `--normalization-mode smart`.
- Unit tests cover common source combinations:
  - H.264 + AC-3 48 kHz
  - H.264 + AAC
  - HEVC + AC-3
  - odd frame rate
  - missing audio
  - multiple audio tracks
  - embedded subtitles

## 16D. Centralize FFmpeg command building

Move FFmpeg command construction into one tested module.

Suggested module:

```text
src/auto_bluray_tui/media/encode.py
```

It should support:

- full transcode
- audio-only transcode
- video copy + audio transcode
- remux/copy
- forced scale/pad
- AC-3 48 kHz output
- NVENC path
- CPU x264 path
- smoke-test encodes
- progress file output
- optional subtitle burn-in
- optional track selection

Acceptance criteria:

- Existing command output is preserved for current default behavior.
- Commands are built as `list[str]`, not shell strings.
- Unit tests verify command construction.
- User paths with spaces/special characters are handled safely.

## 16E. Improve FFmpeg progress parsing

Create a shared progress parser.

Suggested module:

```text
src/auto_bluray_tui/media/progress.py
```

Parse FFmpeg `-progress` files for:

- encoded time
- speed
- fps
- bitrate
- frame count
- output size
- progress=end
- ETA when source duration is known

Acceptance criteria:

- TUI can show better per-title and overall progress.
- Parser is tested using sample progress files.
- Existing progress display does not regress.

## 16F. Add post-encode validation

After every output, run ffprobe and validate against the selected target.

Suggested module:

```text
src/auto_bluray_tui/media/validate.py
```

Validate:

- expected duration
- H.264 video where required
- AC-3 audio where required
- 48 kHz audio
- expected resolution
- frame rate compatibility
- bitrate cap for disc target
- file size
- stream count
- subtitles where expected

Acceptance criteria:

- Invalid outputs fail before tsMuxer.
- Failure messages identify the file, failed rule, observed value, expected value, and suggested fix.
- Existing skip/reuse behavior uses this validator.

## 16G. Use FFmpeg for thumbnails, contact sheets, and previews

Add optional helpers for future menu quality features.

Suggested module:

```text
src/auto_bluray_tui/media/thumbnails.py
```

Use FFmpeg to generate:

- title thumbnails
- chapter thumbnails
- contact sheets
- short silent preview clips
- menu background loops when requested

Acceptance criteria:

- No UI dependency yet; generate assets and report paths.
- Generated assets go under `build/bluray-media/assets/` or another clear build directory.
- Future menu features can consume the generated assets.

## 16H. Use chapter metadata

Use ffprobe chapter data for:

- final report chapter summary
- future scene/chapter menu generation
- tsMuxer chapter metadata when supported

Acceptance criteria:

- Chapter extraction is tested from fixture ffprobe JSON.
- Final report includes chapter counts and chapter timestamps.
- Scene menu feature can later build on this without reparsing media.

## 16I. Improve tsMuxer integration

Create a bounded tsMuxer wrapper.

Suggested module:

```text
src/auto_bluray_tui/authoring/tsmuxer.py
```

It should own:

- track detection
- `.meta` generation
- language tags
- audio delay handling
- SRT/SUP subtitle inclusion where supported
- chapter insertion where supported
- parsing tsMuxer failure output into actionable messages

Acceptance criteria:

- final ISO assembly no longer manually spreads tsMuxer-specific behavior across unrelated modules.
- `.meta` generation is tested as text output.
- tsMuxer errors name the file and likely cause.

## 16J. Add libbluray/VLC smoke validation where practical

Add an optional validation layer after BDMV/ISO creation.

Suggested module:

```text
src/auto_bluray_tui/validate/playback.py
```

Possible checks:

- BDMV tree opens with libbluray/VLC tooling where installed
- title list is discoverable
- playlists exist and can be parsed
- BD-J assets are present
- menu launch can be smoke-tested where possible

Acceptance criteria:

- This is optional and non-blocking unless user enables strict validation.
- Missing VLC/libbluray produces a helpful skipped message.
- Real player testing remains documented separately.

## 16K. Add tests for tool wrappers

Add tests for:

- ffprobe JSON parsing
- compatibility report generation
- copy/remux/transcode planning
- FFmpeg command generation
- FFmpeg progress parsing
- post-encode validation decisions
- tsMuxer `.meta` generation
- chapter extraction

Acceptance criteria:

- Tests use fixture JSON/text.
- Tests do not require real FFmpeg/tsMuxer for unit coverage.
- Integration tests that require real tools are marked or separated.


---

# Phase 6 — Python Package Restructure

## 16. Move source into a real package

Target structure:

```text
src/
  auto_bluray_tui/
    __init__.py
    __main__.py
    cli.py
    launcher.py
    config.py
    paths.py
    diagnostics.py
    dependencies.py
    tui/
      __init__.py
      app.py
      rendering.py
      input.py
    workflow/
      __init__.py
      state.py
      runner.py
      steps.py
    media/
      __init__.py
      discovery.py
      encode.py
      probe.py
    menu/
      __init__.py
      button_action_parser.py
      pptx_converter.py
      backends.py
    burn/
      __init__.py
      devices.py
      burn.py
```

Keep compatibility wrappers:

```text
start.py
install.py
tools/*.py
scripts/*.sh
```

Example `start.py` after migration:

```python
#!/usr/bin/env python3
from auto_bluray_tui.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

Acceptance criteria:

- `python -m auto_bluray_tui --doctor` works.
- `auto-bluray-tui --doctor` works.
- `python start.py --doctor` still works.
- tests import from the package, not by mutating `sys.path` toward `tools/`.
- PyInstaller release still includes required runtime assets.

## 17. Update `pyproject.toml`

Move from loose module packaging to `src` packaging.

Recommended shape:

```toml
[tool.setuptools.packages.find]
where = ["src"]

[project.scripts]
auto-bluray-tui = "auto_bluray_tui.cli:main"
```

Acceptance criteria:

- `python -m pip install -e .` works.
- `python -m unittest discover -s tests` works after editable install.
- no tests depend on manually inserting repository root or `tools/` into `sys.path`.

---

# Phase 7 — Split the TUI Monitor

## 18. Break up `bluray_tui_monitor.py`

Extract in this order:

1. constants and config
2. path helpers
3. JSON state read/write
4. process/PID helpers
5. dependency checks
6. media/progress parsing
7. workflow runner
8. burn state and burner helpers
9. curses rendering/input

Suggested target modules:

```text
auto_bluray_tui/config.py
auto_bluray_tui/workflow/state.py
auto_bluray_tui/workflow/runner.py
auto_bluray_tui/media/progress.py
auto_bluray_tui/dependencies.py
auto_bluray_tui/tui/app.py
```

Acceptance criteria:

- each extracted module has focused tests
- `bluray_tui_monitor.py` becomes a thin compatibility wrapper or is replaced by `auto_bluray_tui.tui.app`
- no behavior change is introduced without tests

---

# Phase 8 — Replace Generated Bash Workflow

## 19. Convert workflow steps to Python objects

Replace generated Bash workflow orchestration with Python-defined steps.

Suggested model:

```python
from dataclasses import dataclass

@dataclass
class WorkflowStep:
    key: str
    label: str
    command: list[str]
    required_tools: list[str]
    optional: bool = False
```

The runner should:

- write workflow state before each step
- stream output to a log file
- capture return code
- stop on failure unless optional
- write structured failure details
- support safe cancellation where practical

Acceptance criteria:

- workflow behavior matches current autopilot
- state file still updates for the TUI
- logs remain readable
- commands use `subprocess.Popen([...])`, not shell string interpolation
- no `bash -lc` is required for the main Python workflow
- shell scripts remain as compatibility wrappers where useful

## 20. Make steps independently runnable/testable

Each workflow step should define:

- inputs
- outputs
- required tools
- skip criteria
- stale-output detection

Acceptance criteria:

- unit tests can mock subprocess and verify step order
- tests can verify failure state if a step exits non-zero
- the workflow runner can resume or rerun safely

---

# Phase 9 — Tests and Fixtures

## 21. Add dependency detection tests

Create tests for:

- macOS Java stub
- missing Java
- working Java
- missing tsMuxer
- wrong-architecture tsMuxer error
- tsMuxer alias names
- missing UDF ISO creator
- xorriso-as-mkisofs fallback

Acceptance criteria:

- tests mock subprocess
- tests do not require real tools installed
- tests run on all CI platforms

## 22. Add workflow runner tests

Mock subprocess and verify:

- step order
- state transitions
- failed step handling
- optional burn failure handling
- cancellation behavior if supported
- log file writes

Acceptance criteria:

- no real ffmpeg, tsMuxer, Java, or burner tools are needed

## 23. Add small project fixtures

Create:

```text
tests/fixtures/
  simple_project/
  multi_video_project/
  subtitle_project/
```

Use tiny placeholders where possible. For media-specific tests requiring ffprobe, mock ffprobe output instead of including real media unless absolutely necessary.

Acceptance criteria:

- tests stay fast
- fixtures are small
- no copyrighted media is included

---

# Phase 10 — User-Facing Disc Authoring Quality

These come from the existing upgrades list and v0.2 P2 roadmap.

## 24. Menu/navigation improvements

Prioritize:

1. scene / chapter menu
2. Play All / Play Selected
3. button focus order editor
4. default selected button
5. Back / Top Menu / Popup Menu buttons
6. thumbnail/contact sheet menu

Suggested PowerPoint hint syntax:

```text
nav: up=Main left=Extras right=Scenes down=Play
```

Acceptance criteria:

- focus order can be explicitly controlled
- default selected button can be set
- automatic fallback still works if no hints are provided
- compatibility report identifies BD-J-only behavior where relevant

## 25. Setup menu improvements

Add support for:

- subtitles
- audio tracks
- commentary
- version variants

Acceptance criteria:

- setup menu can select available subtitle/audio options
- final report shows available variants
- unsupported combinations fail clearly

## 26. Motion menu improvements

Add support for:

- muted motion backgrounds
- optional music/audio background
- video window regions from PowerPoint labels

Acceptance criteria:

- motion menu features are clearly marked BD-J-required until HDMV support is real
- generated compatibility report explains backend limitations

## 27. Better final report / troubleshooting output

Improve final reports with:

- selected backend
- dependency summary
- encoded title summary
- subtitle/audio summary
- menu action summary
- unreachable videos
- stale inputs
- final ISO size/capacity status
- burn readiness

Acceptance criteria:

- user can diagnose most failures from final report and logs
- report is machine-readable JSON plus optional Markdown summary

## 28. Player compatibility matrix and real-player testing

Add `docs/platform-support.md` and `docs/player-compatibility.md`.

Track:

- Linux
- Windows
- macOS Intel
- macOS Apple Silicon
- VLC/libbluray
- at least one real standalone Blu-ray player
- BD-RE tests
- BD-R tests if available

Acceptance criteria:

- known working player/device combinations are documented
- FPS/profile/bitrate fixes are tracked against real tests
- v0.1/v0.2 demo ISO status is recorded

---

# Phase 11 — HDMV Gate 1

HDMV should only move back into active development after the stable BD-J path is strong.

## 29. Minimal HDMV proof target

Produce one static playable menu disc that can:

- open main menu
- choose between two titles
- jump to a title
- return to main menu

Verify in:

- libbluray tooling
- at least one real standalone player

Acceptance criteria:

- static HDMV-safe menu model is accepted
- BD-J-only menu model is rejected or falls back
- existing BD-J backend still builds the same outputs as before
- HDMV compiler status becomes `functional` only after real playback is proven

## 30. Defer until after HDMV Gate 1

Do not spend time on these until the static proof works:

- timestamps/chapter jumps
- resume/replay behavior
- motion menus
- advanced button state behavior
- broad command compiler ambition
- UHD Blu-ray scope

---

# Suggested Codex Task Order

Use this order to avoid destabilizing the app:

1. Add CI test workflow.
2. Update release workflow to depend on tests.
3. Add Ruff baseline.
4. Remove personal paths.
5. Centralize versioning.
6. Unify dependency detection.
7. Add platform-aware tsMuxer detection.
8. Stop Linux tsMuxer download on macOS/Windows.
9. Improve `--doctor`.
10. Add dependency detection tests.
11. Add demo project generator.
12. Add demo smoke build where practical.
13. Add ffprobe media model and compatibility report.
14. Add copy/remux/transcode planning without changing default behavior.
15. Centralize FFmpeg command building.
16. Add FFmpeg progress parser and post-encode validation.
17. Improve tsMuxer wrapper/meta generation.
18. Add optional libbluray/VLC smoke validation.
19. Begin package migration under `src/auto_bluray_tui`.
20. Move button action parser into package and update tests.
21. Move launcher logic into package and update wrappers.
22. Extract workflow state helpers.
23. Extract dependency helpers.
24. Extract media/progress helpers.
25. Split TUI monitor.
26. Replace generated Bash workflow with Python step runner.
27. Add workflow runner tests.
28. Add platform compatibility docs.
29. Add player compatibility docs.
30. Add menu/navigation quality features.
31. Revisit HDMV Gate 1 only after BD-J path is stable.

---

# Definition of Done

The merged plan is complete when:

- existing release artifacts still build
- normal CI runs unit tests on Linux, macOS, and Windows
- release artifacts are not published if tests fail
- `auto-bluray-tui --doctor` works on all target platforms
- macOS Intel and Apple Silicon dependency errors are clear
- public docs/scripts contain no personal paths
- app/package version is centralized
- core Python modules live under `src/auto_bluray_tui`
- ffprobe is the source of truth for media metadata
- FFmpeg command construction, progress parsing, and post-encode validation are centralized and tested
- copy/remux/transcode planning exists, even if smart behavior is initially opt-in
- tsMuxer integration is bounded behind a tested wrapper
- TUI behavior is preserved
- workflow orchestration is mostly Python, not generated Bash
- BD-J remains the shipping backend
- HDMV remains gated until static playback is proven
- Codex can work on one subsystem at a time without editing one giant monitor file

---

# First Codex Prompt

Use this as the first prompt:

```text
Please start with Phase 1 of docs/merged-codex-work-plan.md.

Add a normal GitHub Actions CI workflow that runs the Python unit tests on Linux, macOS, and Windows for Python 3.10, 3.11, and 3.12. Then update the release workflow so release artifacts are only built after tests pass.

Do not refactor application code yet. Keep this PR focused on CI/release safety. Preserve the existing PyInstaller smoke tests. Run the tests locally if possible and include a short summary of changes.
```

---

# Second Codex Prompt

Use this after Phase 1 passes:

```text
Please complete the public polish items from Phase 2 of docs/merged-codex-work-plan.md.

Remove personal/local paths from scripts and docs, require explicit project paths where appropriate, and centralize versioning so package metadata, --doctor output, and release tags do not drift.

Keep compatibility wrappers working. Add or update tests for any changed CLI behavior.
```

---

# Third Codex Prompt

Use this after Phase 2 passes:

```text
Please start Phase 3 of docs/merged-codex-work-plan.md.

Create a shared dependency diagnostics module and move Java, ffmpeg, ffprobe, tsMuxer, ISO tool, LibreOffice, poppler, and Ant checks toward it. Prioritize platform-aware tsMuxer detection and clear macOS Intel/Apple Silicon wrong-architecture messages.

Do not change the core workflow yet. Update --doctor and tests to use the new dependency diagnostics.
```


---

# Fourth Codex Prompt

Use this after dependency diagnostics are stable:

```text
Please start Phase 5B of docs/merged-codex-work-plan.md.

Add an “existing media tools first” layer. Start by creating an ffprobe media model and compatibility report module. ffprobe should become the source of truth for media metadata. Then add a planning module that can decide whether each input needs copy, remux, audio-only transcode, or full transcode.

Do not change the default encode behavior yet. First add structured reports and tests using fixture ffprobe JSON. Keep this PR focused on media probing, reporting, and planning.
```
