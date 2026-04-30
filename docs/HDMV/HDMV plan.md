Roadmap				
v0.1	Keep BD-J only. Stabilize current workflow. Add compatibility matrix.			
v0.2	Refactor PowerPoint extraction into neutral menu-model JSON.			
v0.3	Add menu_backend setting, TUI toggle, BD-J backend wrapper, HDMV placeholder, compatibility report.			
v0.4	Add HDMV export package: backgrounds, button maps, playlists, chapter maps, authoring report.			
v0.5	Attempt HDMV-Lite static top menu generation.			
v0.6	Add scene/chapter menus in HDMV-Lite.			
v0.7	Add subtitle/audio setup menus.			
v1.0	Default to HDMV for simple discs, BD-J for advanced/motion/interactive discs.			
step zero	gpt research HDMV			
step 0.5	openclaw hdmv.md			
first prompt				
Add a menu backend architecture so Auto Blu-ray TUI can support both HDMV and BD-J menus.				
				
Current behavior is BD-J/GRIN-based. Refactor the PowerPoint menu conversion so it first emits a backend-neutral menu model JSON containing slides, backgrounds, buttons, hitboxes, focus order, actions, video targets, playlists, and feature requirements.				
				
Then add a backend selector with values: hdmv, bdj, auto. Default should be hdmv. Auto should choose HDMV when the menu uses only HDMV-safe features, and fall back to BD-J when BD-J-only features are detected.				
				
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
