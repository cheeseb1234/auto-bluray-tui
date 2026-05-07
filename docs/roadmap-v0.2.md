# Auto Blu-ray TUI v0.2 roadmap

## Product stance

v0.2 should optimize for **a reliable, practical Blu-ray authoring workflow**, not for maximum backend experimentation.

### Working promise

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

## Strategic decisions

### Keep and strengthen

- backend-neutral `menu-model.json`
- BD-J / GRIN as the shipping backend
- PowerPoint-first authoring workflow
- explicit compatibility reporting for future HDMV work

### Freeze for now

Treat HDMV as **research/export mode**, not as a shipping backend.

That means:

- keep HDMV IR/package export work
- keep compatibility analysis
- keep validation runbooks
- do **not** market HDMV as a working final menu path yet

## v0.2 priorities

### P0 — release/runtime reliability

1. **Packaged app works without Python hand-fixing**
   - helper shell scripts must use the packaged Python runtime
   - bundled Python dependencies such as `requests` must be available end-to-end

2. **Actionable dependency diagnostics**
   - `--doctor` on packaged builds
   - clear macOS fixes for Java, `xorriso`, and `tsMuxer`
   - detect Apple's `/usr/bin/java` stub correctly

3. **Early TUI preflight warnings**
   - warn before starting work if `tsMuxer` is missing
   - warn before burning if `xorriso` is missing
   - flag `requests` availability when OpenSubtitles fetching is enabled

4. **Packaged-release smoke tests**
   - `auto-bluray-tui --help`
   - `auto-bluray-tui --doctor`
   - at least one non-interactive project analysis smoke test where practical

### P1 — known-good authoring path

1. **Golden demo project**
   - tiny sample project committed or generated
   - known-good expected ISO/report outputs

2. **Demo smoke build in CI**
   - menu conversion
   - media analysis
   - authoring plan generation
   - BD-J menu build

3. **Error-message cleanup**
   - common failure points should name the failing tool and exact remediation
   - avoid misleading “found but broken” wording when the runtime is actually missing

### P2 — user-facing disc authoring quality

1. button focus override / navigation hints
2. default selected button
3. setup menu for subtitle/audio/version variants
4. stronger compatibility matrix and player notes
5. better final report / troubleshooting output

## HDMV plan for later

HDMV should only move back into active development after a minimal proof target is met.

### HDMV Gate 1

Produce one **static** playable menu disc that can:

- open main menu
- choose between two titles
- jump to a title
- return to main menu

And verify it in:

- libbluray tooling
- at least one real standalone player

### Defer until after Gate 1

- timestamps/chapter jumps
- resume/replay behavior
- motion menus
- advanced button state behavior beyond static needs
- broader command compiler ambition
- UHD Blu-ray scope

## What v0.2 should not try to do

- full HDMV parity with BD-J
- UHD Blu-ray authoring
- complicated menu DSL expansion before the core workflow is stable
- platform-specific dependency mysteries hidden from the user

## Definition of done for v0.2

A reasonable new user on macOS or Linux can:

1. run the packaged app
2. run `--doctor` and understand what is missing
3. fix dependencies with exact commands
4. launch the TUI
5. build a BD-J-backed Blu-ray ISO from a normal project folder

without manually debugging Python packaging or hidden helper-runtime issues.
