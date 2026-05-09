> Historical HDMV-specific planning note. The current authoritative merged execution plan is `docs/merged-codex-work-plan.md`. HDMV remains gated behind the later HDMV proof milestone described there.

Roadmap
v0.1	Keep BD-J only. Stabilize current workflow. Add compatibility matrix.
v0.2	Refactor PowerPoint extraction into neutral menu-model JSON.
v0.3	Add menu_backend setting, TUI toggle, BD-J backend wrapper, HDMV placeholder, compatibility report.
v0.4	DONE: Add HDMV-Lite export package: copied static backgrounds, button maps, playlists/title refs, index/MovieObject XML skeletons, authoring report.
v0.5	IN PROGRESS: Replace placeholder MovieObject commands and add real IG stream compilation for HDMV-Lite static menu playback.
v0.6	Add scene/chapter menus in HDMV-Lite.
v0.7	Add subtitle/audio setup menus.
v1.0	Consider defaulting to HDMV for simple discs only after HDMV compiler_status is functional; BD-J/GRIN remains the working default until then.
step zero	gpt research HDMV
step 0.5	openclaw hdmv.md
first prompt
Add a menu backend architecture so Auto Blu-ray TUI can support both HDMV and BD-J menus.

Current behavior is BD-J/GRIN-based. Refactor the PowerPoint menu conversion so it first emits a backend-neutral menu model JSON containing slides, backgrounds, buttons, hitboxes, focus order, actions, video targets, playlists, and feature requirements.

Then add a backend selector with values: hdmv, bdj, auto. Current default should remain bdj because BD-J/GRIN is the working backend. Auto should not choose HDMV as the final backend until HDMV compiler_status is functional; before that, HDMV stays available as an experimental export/scaffold path.

Do not attempt full HDMV support in the first pass. Implement an HDMV-Lite roadmap and scaffolding:
1. Create MenuBackend interface.
2. Move current GRIN/BD-J install/build behavior behind BdjMenuBackend.
3. Add HdmvMenuBackend placeholder that validates whether a menu is HDMV-safe and fails with a clear message if actual HDMV compilation is not implemented yet.
4. Add compatibility report output showing which menu features are HDMV-safe and which require BD-J.
5. Update the TUI to show and persist menu_backend.
6. Update docs to explain HDMV vs BD-J tradeoffs and the current implementation status.

Prioritize clean architecture, tests, and no regression to the existing BD-J workflow.

second prompt
Implement the first HDMV-Lite backend milestone.

Scope:
- static top menu only
- one background image
- button hitboxes from the neutral menu model
- simple actions: play title, go to another menu, return to main menu
- no motion video windows
- no Java
- fail clearly for unsupported features

Add a demo project and tests that prove:
- HDMV-safe menu model is accepted
- BD-J-only menu model is rejected or falls back
- existing BD-J backend still builds the same outputs as before
