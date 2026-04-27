# Blu-ray Interactive Menu Authoring with HD Cook Book

This repo is an archive of the old java.net projects. The HD Cook Book code lives in the `hdcookbook/` subdirectory, not at repository root.

## Quick start

From this `hdcookbook/` directory:

```bash
./scripts/build-sample-disc.sh
```

The script uses local JDK 8 + Ant if available. If not, it builds/runs a small Docker image with JDK 8 and Ant.

Expected output:

- Tools and Xlets compile under `build/`
- Sample disc overlay is zipped as `xlets/hdcookbook_discimage/HDCookbookDiscImage.zip`

Verified on Manjaro/Arch with `jdk8-openjdk` + `ant` installed. The build emits old-signing warnings because the sample BD-J signing flow uses legacy SHA-1/1024-bit test certificates, but the sample overlay still builds successfully.

The upstream sample needs the static video/disc-image base from the archived release mentioned by the Ant build. The zip produced here contains the Java/BD-J overlay that is unzipped over that base BDMV directory.

## Where the interactive menu lives

Main sample menu files:

- `xlets/hdcookbook_discimage/bookmenu/src/com/hdcookbook/bookmenu/assets/menu.txt` — GRIN menu/show script
- `xlets/hdcookbook_discimage/bookmenu/src/com/hdcookbook/bookmenu/assets/mosaics.txt` — image mosaic packing config
- `xlets/hdcookbook_discimage/bookmenu/src/com/hdcookbook/bookmenu/menu/MenuXlet.java` — BD-J Xlet entry point
- `xlets/hdcookbook_discimage/bookmenu/src/com/hdcookbook/bookmenu/menu/MenuDirector.java` — menu logic/director
- `xlets/hdcookbook_discimage/bookmenu/src/com/hdcookbook/bookmenu/menu/MenuDiscNavigator.java` — playlist/title navigation glue

The important build flow is:

1. `menu.txt` is compiled by the GRIN binary converter.
2. Generated Java lands under `build/xlets/menu_generated/`.
3. The menu Xlet is packaged as `BDMV/JAR/00002.jar`.
4. BDJO/BDMV metadata is generated and the Xlets are signed.
5. The overlay BDMV tree is zipped.

## Practical editing path

For a custom disc menu, start by copying the existing `bookmenu` sample rather than writing a BD-J Xlet from scratch.

Recommended first pass:

1. Replace menu artwork in the `assets/Graphics/` tree.
2. Edit labels and segments in `assets/menu.txt`.
3. Keep the existing remote-control handlers until the first build works.
4. Adjust `MenuDiscNavigator.java` only after the visual menu compiles.
5. Build with `./scripts/build-sample-disc.sh` after each meaningful change.

## Local prerequisites

HD Cook Book is old BD-J code. It is happiest with:

- JDK 8
- Apache Ant
- BD-J platform stubs

The archived repository already contains BD-J stub classes at:

```text
lib/stubs/enhanced/classes.zip
```

`user.vars.properties.example` points the build at those stubs. The build script copies it to `user.vars.properties` automatically when needed.
