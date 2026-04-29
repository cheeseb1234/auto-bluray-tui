# SlidesMenu — PowerPoint-style Blu-ray menu sample

This is the second, more user-friendly menu version. It keeps the original HD Cookbook sample untouched and adds a slide/page model that is easier to author.

## Edit pages

Edit `slides.json`:

- each slide is a menu page
- `title`, `subtitle`, `body`, `background`, and `accent` control the look
- each button has `label`, `target`, and a rectangle: `x`, `y`, `w`, `h`

## Generate and preview

```bash
cd hdcookbook/xlets/grin_samples/Scripts/SlidesMenu
ant preview
```

That generates:

- `slides-menu.txt` — GRIN show script
- `assets/*_bg.png` — full-screen slide backgrounds
- `assets/*_selected.png` / `*_activated.png` — button focus overlays

Then it launches GRINView.

## Build the Xlet jar

```bash
ant
```

The output is:

```text
build/00000.jar
```

## Design intent

This is intentionally PowerPoint-like: author pages, titles, body text, custom colors/backgrounds, and clickable/remote-selectable buttons first. The generator emits the older GRIN syntax underneath.
