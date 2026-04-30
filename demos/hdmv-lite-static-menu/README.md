# HDMV-Lite static menu demo

This is a tiny backend-neutral demo model for the first HDMV-Lite milestone.
It intentionally avoids PowerPoint/media binaries so it can stay in git.

It demonstrates the supported subset:

- static menu pages
- one rendered background image per page
- rectangular button hitboxes from the neutral model
- `play_title`, `go_to_menu`, and `return_main_menu` actions
- no Java, no motion/video-window menu features

The model can be used by unit tests or copied into a generated `PptxMenu`
folder to exercise `HdmvMenuBackend` directly. A full final-disc build still
requires real project media and the normal PowerPoint conversion pipeline.
