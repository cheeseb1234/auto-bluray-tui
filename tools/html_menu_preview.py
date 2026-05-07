#!/usr/bin/env python3
"""Generate a standalone-ish local HTML simulator for a PPTX-derived Blu-ray menu.

The preview consumes the backend-neutral PptxMenu/menu-model.json emitted by
pptx_menu_converter.py and renders PowerPoint slide PNGs with clickable hitboxes,
keyboard/remote-style arrow navigation, action target inspection, and a live
validation/info panel beside the slide.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import webbrowser
from pathlib import Path
from typing import Any

VIDEO_SUFFIXES = {'.mp4', '.mkv', '.m2ts', '.mov'}


def button_center(button: dict[str, Any]) -> tuple[float, float]:
    r = button.get('hitbox_px') or button.get('rect_px') or {}
    return (float(r.get('x', 0)) + float(r.get('w', 0)) / 2, float(r.get('y', 0)) + float(r.get('h', 0)) / 2)


def row_order(buttons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for btn in sorted(buttons, key=lambda b: (button_center(b)[1], button_center(b)[0])):
        cy = button_center(btn)[1]
        placed = False
        for row in rows:
            row_cy = sum(button_center(b)[1] for b in row) / len(row)
            row_h = max((b.get('hitbox_px') or b.get('rect_px') or {}).get('h', 0) for b in row)
            if abs(cy - row_cy) <= max(40, row_h * 0.45):
                row.append(btn)
                placed = True
                break
        if not placed:
            rows.append([btn])
    return [btn for row in rows for btn in sorted(row, key=lambda b: button_center(b)[0])]


def build_validation(model: dict[str, Any], project_dir: Path | None) -> tuple[list[str], dict[str, Any]]:
    slides = {s['id']: s for s in model.get('slides', [])}
    declared_videos = sorted(set(model.get('videos', {}).values()))
    reachable_videos: set[str] = set()
    reachable_slides: set[str] = {'slide1'} if 'slide1' in slides else set()
    lines = ['Menu validation', '---------------']
    warnings: list[str] = []
    errors = 0

    for slide in model.get('slides', []):
        lines.append(f"{slide['id']}:")
        buttons = row_order(slide.get('buttons', []))
        if not buttons:
            lines.append(' (no buttons) ⚠️')
        for btn in buttons:
            label = btn.get('label') or btn.get('id') or '(unnamed)'
            action = btn.get('action') or {}
            kind = action.get('kind') or action.get('type') or 'unknown'
            if kind == 'slide':
                target = action.get('target') or action.get('menu_target')
                ok = target in slides
                if ok:
                    reachable_slides.add(target)
                else:
                    errors += 1
                lines.append(f" {label} -> {target or 'missing slide target'} {'✅' if ok else '❌'}")
            elif kind == 'video':
                target = action.get('target') or action.get('video_file') or action.get('video_target')
                exists = True
                if project_dir and target:
                    exists = (project_dir / target).exists()
                ok = bool(target) and exists
                if ok:
                    reachable_videos.add(target)
                else:
                    errors += 1
                suffix = '✅' if ok else '❌'
                if target and project_dir and not exists:
                    lines.append(f" {label} -> {target} {suffix} (missing file)")
                else:
                    chapter = f" @{action.get('start_timecode')}" if action.get('start_time_seconds') else ''
                    lines.append(f" {label} -> {target or 'missing video target'}{chapter} {suffix}")
            else:
                errors += 1
                warnings.append(f'Button "{label}" does not have a recognized action target.')
                lines.append(f" {label} -> unknown action ❌")
        lines.append('')

    for slide_id in sorted(set(slides) - reachable_slides):
        if slide_id != 'slide1':
            warnings.append(f'Slide "{slide_id}" is not reachable from slide1 by detected menu buttons.')

    for video in declared_videos:
        if video not in reachable_videos:
            warnings.append(f'Video "{video}" is not reachable from any menu.')

    if model.get('match_warnings'):
        for item in model['match_warnings']:
            warnings.append(f"{item.get('slide', '?')}: {item.get('message', 'match warning')}")

    lines.append('Warnings:')
    if warnings:
        lines.extend(f' {w}' for w in warnings)
    else:
        lines.append(' None ✅')

    summary = {'errors': errors, 'warnings': len(warnings), 'reachable_videos': sorted(reachable_videos), 'reachable_slides': sorted(reachable_slides)}
    return lines, summary


def make_preview(model_path: Path, output: Path, project_dir: Path | None) -> None:
    model = json.loads(model_path.read_text())
    base = model_path.parent
    validation_lines, validation_summary = build_validation(model, project_dir)
    asset_root = Path('.')
    try:
        asset_root = Path(base.relative_to(output.parent))
    except ValueError:
        asset_root = Path(os.path.relpath(base, output.parent))

    for slide in model.get('slides', []):
        slide['preview_order'] = [b.get('id') for b in row_order(slide.get('buttons', []))]

    payload = {
        'model': model,
        'validationText': '\n'.join(validation_lines),
        'validationSummary': validation_summary,
        'baseNote': f'Preview generated from {model_path}',
        'assetRoot': asset_root.as_posix(),
    }
    json_payload = json.dumps(payload, ensure_ascii=False)
    safe_json_payload = json_payload.replace('</', '<\\/')
    title = html.escape(f"Blu-ray menu preview - {Path(model.get('source', 'menu.pptx')).name}")

    html_doc = f"""<!doctype html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; --accent:#45ffa9; --focus:#fff; --warn:#ffcf5a; --bad:#ff6b6b; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#111; color:#eee; font:14px/1.4 system-ui, Segoe UI, sans-serif; display:grid; grid-template-rows:auto 1fr auto; min-height:100vh; }}
  header, footer {{ padding:.65rem 1rem; background:#181818; border-color:#333; }}
  header {{ border-bottom:1px solid #333; display:flex; gap:1rem; align-items:center; flex-wrap:wrap; }}
  footer {{ border-top:1px solid #333; color:#aaa; }}
  button {{ background:#2a2a2a; color:#eee; border:1px solid #555; border-radius:.45rem; padding:.35rem .65rem; cursor:pointer; }}
  button:hover {{ border-color:#aaa; }}
  #stageWrap {{ display:grid; grid-template-columns:minmax(320px, 440px) minmax(640px, 1fr); gap:1rem; align-items:start; padding:1rem; overflow:auto; }}
  #infoPanel {{ min-height: min(72vh, 800px); background:#10141a; border:1px solid #333; border-radius:.75rem; padding:1rem; box-shadow:0 12px 48px #0006; }}
  #stage {{ position:relative; width:min(100%, 1280px); aspect-ratio:16/9; background:#050505; box-shadow:0 12px 48px #000a; overflow:hidden; justify-self:start; }}
  @media (max-width: 1000px) {{ #stageWrap {{ grid-template-columns:1fr; }} #stage {{ justify-self:center; }} }}
  #bg {{ position:absolute; inset:0; width:100%; height:100%; object-fit:fill; user-select:none; }}
  .hitbox {{ position:absolute; border:2px dashed rgba(255,207,90,.35); background:rgba(255,207,90,.08); opacity:0; transition:opacity .08s, box-shadow .08s, border-color .08s; cursor:pointer; }}
  body.show-hitboxes .hitbox {{ opacity:1; }}
  .hitbox.focused {{ opacity:1; border:4px solid var(--focus); background:rgba(255,255,255,.08); box-shadow:0 0 0 4px rgba(0,0,0,.55), 0 0 22px rgba(255,255,255,.55); }}
  .hitbox.activated {{ border-color:var(--accent); box-shadow:0 0 24px rgba(69,255,169,.8); }}
  .label {{ position:absolute; left:0; top:100%; transform:translateY(4px); background:#000c; color:#fff; border-radius:.25rem; padding:.15rem .35rem; white-space:nowrap; font-size:12px; pointer-events:none; }}
  #toast {{ position:absolute; left:50%; bottom:1.2rem; transform:translateX(-50%); max-width:min(90%, 900px); background:#000d; border:1px solid #555; border-radius:.6rem; padding:.75rem 1rem; box-shadow:0 8px 30px #000c; display:none; }}
  #validation {{ white-space:pre-wrap; font:18px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color:#eee; margin:0; }}
  .pill {{ display:inline-flex; gap:.35rem; align-items:center; border:1px solid #444; border-radius:999px; padding:.2rem .55rem; color:#ccc; }}
  .ok {{ color:var(--accent); }} .warn {{ color:var(--warn); }} .bad {{ color:var(--bad); }}
  kbd {{ background:#333; border:1px solid #555; border-bottom-color:#222; border-radius:.25rem; padding:.05rem .3rem; }}
</style>
</head>
<body class=\"show-hitboxes\">
<header>
  <strong>Blu-ray menu HTML preview</strong>
  <span id=\"crumb\" class=\"pill\"></span>
  <button id=\"prevBtn\" type=\"button\">◀ Slide</button>
  <button id=\"nextBtn\" type=\"button\">Slide ▶</button>
  <button id=\"hitboxBtn\" type=\"button\">Toggle hitboxes</button>
  <span class=\"pill\"><kbd>←↑↓→</kbd> focus <kbd>Enter</kbd> activate <kbd>Esc</kbd> main</span>
</header>
<main id=\"stageWrap\">
  <aside id=\"infoPanel\" aria-label=\"menu validation and action info\">
    <pre id=\"validation\"></pre>
  </aside>
  <section id=\"stage\" aria-label=\"menu preview\">
    <img id=\"bg\" alt=\"rendered PowerPoint slide\">
    <div id=\"buttons\"></div>
    <div id=\"toast\"></div>
  </section>
</main>
<footer id=\"status\"></footer>
<script id=\"preview-data\" type=\"application/json\">{safe_json_payload}</script>
<script>
const data = JSON.parse(document.getElementById('preview-data').textContent);
const model = data.model;
const slides = new Map(model.slides.map(s => [s.id, s]));
let slideId = model.slides[0]?.id || 'slide1';
let focused = 0;
const bg = document.getElementById('bg');
const stage = document.getElementById('stage');
const buttonsEl = document.getElementById('buttons');
const toast = document.getElementById('toast');
const validation = document.getElementById('validation');
const crumb = document.getElementById('crumb');
const statusEl = document.getElementById('status');

function relAsset(file) {{
  const root = data.assetRoot || '.';
  return `${{root}}/${{file || `assets/${{slideId}}_bg.png`}}`;
}}
function orderedButtons(slide) {{
  const map = new Map((slide.buttons || []).map(b => [b.id, b]));
  const order = (slide.preview_order || []).map(id => map.get(id)).filter(Boolean);
  return order.length ? order : (slide.buttons || []);
}}
function showToast(text) {{
  toast.textContent = text;
  toast.style.display = 'block';
  clearTimeout(showToast.t);
  showToast.t = setTimeout(() => toast.style.display = 'none', 4500);
}}
function render() {{
  const slide = slides.get(slideId) || model.slides[0];
  slideId = slide.id;
  const btns = orderedButtons(slide);
  if (focused >= btns.length) focused = Math.max(0, btns.length - 1);
  bg.hidden = false; buttonsEl.hidden = false;
  validation.textContent = data.validationText;
  bg.src = relAsset(slide.background?.file || `assets/${{slide.id}}_bg.png`);
  buttonsEl.innerHTML = '';
  const w = slide.background?.width || model.coordinate_spaces?.rendered_px?.width || 1920;
  const h = slide.background?.height || model.coordinate_spaces?.rendered_px?.height || 1080;
  btns.forEach((btn, i) => {{
    const r = btn.hitbox_px || btn.rect_px;
    const el = document.createElement('button');
    el.className = 'hitbox' + (i === focused ? ' focused' : '');
    el.style.left = `${{100 * r.x / w}}%`;
    el.style.top = `${{100 * r.y / h}}%`;
    el.style.width = `${{100 * r.w / w}}%`;
    el.style.height = `${{100 * r.h / h}}%`;
    el.title = actionText(btn);
    el.setAttribute('aria-label', `${{btn.label}}: ${{actionText(btn)}}`);
    const label = document.createElement('span'); label.className = 'label'; label.textContent = btn.label; el.append(label);
    el.addEventListener('mouseenter', () => {{ focused = i; updateFocus(); }});
    el.addEventListener('click', () => activate(i));
    buttonsEl.append(el);
  }});
  crumb.textContent = `${{slide.id}} — ${{slide.title || 'Untitled'}}`;
  statusEl.textContent = `${{data.baseNote}} · ${{btns.length}} buttons · validation: ${{data.validationSummary.errors}} errors, ${{data.validationSummary.warnings}} warnings`;
}}
function actionText(btn) {{
  const a = btn.action || {{}};
  if (a.kind === 'slide') return `go to ${{a.target}}`;
  if (a.kind === 'video') {{ const start = a.start_time_seconds ? ` @ ${{a.start_timecode || a.start_time_seconds + 's'}}` : ''; return `play ${{a.target || a.video_file}}${{start}} (playlist ${{a.playlist_id || a.playlist || 'n/a'}})`; }}
  return 'unknown action';
}}
function updateFocus() {{ [...buttonsEl.children].forEach((el, i) => el.classList.toggle('focused', i === focused)); }}
function activate(i = focused) {{
  const slide = slides.get(slideId); const btn = orderedButtons(slide)[i]; if (!btn) return;
  const el = buttonsEl.children[i]; el?.classList.add('activated'); setTimeout(() => el?.classList.remove('activated'), 220);
  const a = btn.action || {{}};
  if (a.kind === 'slide' && slides.has(a.target)) {{ slideId = a.target; focused = 0; render(); return; }}
  if (a.kind === 'video') {{ const start = a.start_time_seconds ? ` @ ${{a.start_timecode || a.start_time_seconds + 's'}}` : ''; showToast(`Action target: ${{btn.label}} → ${{a.target || a.video_file}}${{start}} · playlist ${{a.playlist_id || a.playlist || 'n/a'}}`); return; }}
  showToast(`No valid action for ${{btn.label}}`);
}}
function move(dir) {{
  const slide = slides.get(slideId); const btns = orderedButtons(slide); if (!btns.length) return;
  const cur = btns[focused]; const cr = cur.hitbox_px || cur.rect_px; const cx = cr.x + cr.w/2, cy = cr.y + cr.h/2;
  let best = -1, bestScore = Infinity;
  btns.forEach((b, i) => {{ if (i === focused) return; const r = b.hitbox_px || b.rect_px; const x = r.x + r.w/2, y = r.y + r.h/2; const dx = x-cx, dy = y-cy;
    if ((dir==='left' && dx >= -5) || (dir==='right' && dx <= 5) || (dir==='up' && dy >= -5) || (dir==='down' && dy <= 5)) return;
    const primary = (dir==='left'||dir==='right') ? Math.abs(dx) : Math.abs(dy);
    const secondary = (dir==='left'||dir==='right') ? Math.abs(dy) : Math.abs(dx);
    const score = primary + secondary * 2.2;
    if (score < bestScore) {{ bestScore = score; best = i; }}
  }});
  if (best >= 0) {{ focused = best; updateFocus(); }}
}}
function stepSlide(delta) {{
  const ids = model.slides.map(s => s.id); let idx = ids.indexOf(slideId); if (idx < 0) idx = 0;
  slideId = ids[(idx + delta + ids.length) % ids.length]; focused = 0; render();
}}
document.addEventListener('keydown', e => {{
  const keys = {{ArrowLeft:'left', ArrowRight:'right', ArrowUp:'up', ArrowDown:'down'}};
  if (keys[e.key]) {{ e.preventDefault(); move(keys[e.key]); }}
  else if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); activate(); }}
  else if (e.key === 'Escape' || e.key === 'Backspace') {{ e.preventDefault(); slideId = 'slide1'; focused = 0; render(); }}
  else if (e.key.toLowerCase() === 'h') {{ document.body.classList.toggle('show-hitboxes'); }}
}});
document.getElementById('prevBtn').onclick = () => stepSlide(-1);
document.getElementById('nextBtn').onclick = () => stepSlide(1);
document.getElementById('hitboxBtn').onclick = () => document.body.classList.toggle('show-hitboxes');
render();
</script>
</body>
</html>
"""
    output.write_text(html_doc)


def main() -> None:
    ap = argparse.ArgumentParser(description='Generate a local HTML preview for a PPTX Blu-ray menu model.')
    ap.add_argument('menu_model', type=Path, help='Path to generated menu-model.json')
    ap.add_argument('-o', '--output', type=Path, help='Output preview HTML path; defaults next to menu-model.json')
    ap.add_argument('--project-dir', type=Path, help='Original Blu-ray project directory for video existence checks')
    ap.add_argument('--no-open', action='store_true', help='Create the preview without launching it in the default browser')
    args = ap.parse_args()
    out = args.output or (args.menu_model.parent / 'menu-preview.html')
    make_preview(args.menu_model.resolve(), out.resolve(), args.project_dir.resolve() if args.project_dir else None)
    print(out.resolve())
    if not args.no_open:
        webbrowser.open(out.resolve().as_uri())


if __name__ == '__main__':
    main()
