#!/usr/bin/env python3
"""Menu backend selection and HDMV/BD-J scaffolding.

The PowerPoint converter produces a backend-neutral menu model.  This module
keeps backend-specific build/install logic out of the converter so the project
can grow from today's GRIN/BD-J implementation toward HDMV-Lite.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import zipfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw

MENU_BACKENDS = ('bdj', 'hdmv', 'auto')
DEFAULT_MENU_BACKEND = 'bdj'
HDMV_COMPILER_STATUS = 'ir_only_first_milestone'
HDMV_FUNCTIONAL_COMPILER_STATUSES = {'functional'}


@dataclass(frozen=True)
class HdmvOpcodeSpec:
    op: str
    mode: str
    compiler: Callable[[dict[str, Any], dict[str, Any]], str | None] | None = None
    note: str = ''


def _compile_jump_title_word(row: dict[str, Any], intended: dict[str, Any]) -> str:
    title_number = int(
        intended.get('target_title_number')
        or row.get('target_title_number')
        or 1
    )
    return f'21810000 {title_number:08x} 00000000'


HDMV_MOVIEOBJECT_OPCODE_REGISTRY: dict[str, HdmvOpcodeSpec] = {
    'JumpTitle': HdmvOpcodeSpec(
        op='JumpTitle',
        mode='native',
        compiler=_compile_jump_title_word,
        note='Trusted public/sample-backed word pattern from local HD Cook Book MovieObject.xml.',
    ),
    'JumpObject': HdmvOpcodeSpec(
        op='JumpObject',
        mode='fallback',
        note='Intent is preserved, but no trusted public byte-level mapping is implemented yet.',
    ),
    'SetButtonPage': HdmvOpcodeSpec(
        op='SetButtonPage',
        mode='fallback',
        note='Intent is preserved, but no trusted public byte-level mapping is implemented yet.',
    ),
    'Nop': HdmvOpcodeSpec(
        op='Nop',
        mode='fallback',
        note='Kept explicit in the graph, but no standalone Nop word is emitted yet.',
    ),
}


class MenuBackendError(RuntimeError):
    """Raised when a selected menu backend cannot build/install the menu."""


class MenuBackend(ABC):
    """Backend interface for authoring a neutral menu model onto a Blu-ray tree."""

    name: str
    description: str

    @abstractmethod
    def install(self, *, root: Path, project: Path, menu_dir: Path, disc_root: Path, output_root: Path, model: dict[str, Any]) -> dict[str, Any]:
        """Build/install backend artifacts into ``disc_root`` and return metadata."""


def run(cmd, **kwargs):
    print('+', ' '.join(str(x) for x in cmd), flush=True)
    return subprocess.run([str(x) for x in cmd], check=True, **kwargs)


def load_menu_model(menu_dir: Path) -> dict[str, Any]:
    path = menu_dir / 'menu-model.json'
    if not path.exists():
        raise MenuBackendError(f'Missing neutral menu model: {path}')
    return json.loads(path.read_text())


def _feature(status: str, feature: str, detail: str, *, hdmv_phase: str | None = None) -> dict[str, Any]:
    row = {'feature': feature, 'status': status, 'detail': detail}
    if hdmv_phase:
        row['hdmv_lite_phase'] = hdmv_phase
    return row


def analyze_menu_compatibility(model: dict[str, Any]) -> dict[str, Any]:
    """Return an HDMV-vs-BD-J compatibility report for a neutral menu model."""
    slides = model.get('slides') or []
    buttons = [b for slide in slides for b in slide.get('buttons', [])]
    loop_videos = [loop for slide in slides for loop in slide.get('loop_videos', [])]
    actions = [b.get('action') or {} for b in buttons]

    safe: list[dict[str, Any]] = []
    bdj_required: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []

    if slides:
        safe.append(_feature('hdmv_safe', 'static_slide_backgrounds', f'{len(slides)} rendered static slide background(s).', hdmv_phase='v0.5'))
    else:
        unsupported.append(_feature('unsupported', 'slides', 'Menu model contains no slides.'))

    # Preflight callers may analyze the raw PPTX extraction before backgrounds are rendered.
    # Once a neutral model declares background records, every slide must have one.
    if any('background' in s for s in slides):
        missing_backgrounds = [s.get('id') for s in slides if not (s.get('background') or {}).get('file')]
        if missing_backgrounds:
            unsupported.append(_feature('unsupported', 'background_assets', 'Slides missing rendered background assets: ' + ', '.join(str(x) for x in missing_backgrounds[:8])))

    if buttons:
        safe.append(_feature('hdmv_safe', 'button_hitboxes', f'{len(buttons)} rectangular button hitbox(es).', hdmv_phase='v0.5'))
        safe.append(_feature('hdmv_safe', 'focus_order', 'Focus order is derived from button geometry and can map to HDMV neighbor navigation.', hdmv_phase='v0.5'))
    else:
        unsupported.append(_feature('unsupported', 'buttons', 'Menu model contains no buttons.'))

    video_actions = [a for a in actions if a.get('kind') == 'video']
    slide_actions = [a for a in actions if a.get('kind') == 'slide']
    builtin_actions = [a for a in actions if a.get('kind') == 'builtin']
    other_actions = [a for a in actions if a.get('kind') not in ('video', 'slide', 'builtin')]
    if video_actions:
        simple_video = [a for a in video_actions if not (a.get('start_time_seconds') or a.get('chapter') or a.get('chapter_name') or a.get('chapter_number'))]
        timed_or_chapter = [a for a in video_actions if a not in simple_video]
        if simple_video:
            safe.append(_feature('hdmv_safe', 'play_title_actions', f'{len(simple_video)} play-title action(s) targeting Blu-ray playlist ids.', hdmv_phase='v0.5'))
        if timed_or_chapter:
            bdj_required.append(_feature('bdj_required', 'timed_or_chapter_video_actions', f'{len(timed_or_chapter)} timestamp/chapter start action(s) are BD-J-supported metadata today; HDMV-Lite command compilation for them is future work.', hdmv_phase='future'))
    if slide_actions:
        safe.append(_feature('hdmv_safe', 'menu_page_navigation', f'{len(slide_actions)} go-to-menu/page action(s).', hdmv_phase='v0.5'))
    if builtin_actions:
        safe_names = {'main', 'top_menu', 'disabled', 'none'}
        safe_builtins = [a for a in builtin_actions if a.get('name') in safe_names]
        future_builtins = [a for a in builtin_actions if a.get('name') in {'back', 'play_all'}]
        bdj_builtins = [a for a in builtin_actions if a.get('name') in {'resume', 'replay'}]
        unknown_builtins = [a for a in builtin_actions if a not in safe_builtins + future_builtins + bdj_builtins]
        if safe_builtins:
            safe.append(_feature('hdmv_safe', 'safe_builtin_actions', 'Built-in main/top-menu/disabled/none actions do not require BD-J-only playback logic.', hdmv_phase='v0.5'))
        if future_builtins:
            bdj_required.append(_feature('bdj_required', 'future_builtin_actions', 'Built-in back/play-all actions need final HDMV command behavior before HDMV-Lite can author them.', hdmv_phase='future'))
        if bdj_builtins:
            bdj_required.append(_feature('bdj_required', 'bdj_runtime_builtin_actions', 'Built-in resume/replay actions require BD-J/runtime playback state in the current implementation.'))
        for action in unknown_builtins:
            unsupported.append(_feature('unsupported', 'unknown_builtin_action', f'Unknown built-in action: {action.get("name")!r}.'))
    for action in other_actions:
        bdj_required.append(_feature('bdj_required', 'custom_action', f'Unsupported action kind for HDMV-Lite scaffold: {action.get("kind")!r}.'))

    if loop_videos or any(s.get('menu_loop_video') for s in slides):
        bdj_required.append(_feature('bdj_required', 'motion_or_windowed_menu_video', 'Looping/menu-window video currently uses Java media control in the BD-J backend.'))
    if any(b.get('normal_overlay') for b in buttons):
        bdj_required.append(_feature('bdj_required', 'button_graphics_over_video_window', 'Normal-state button overlays over transparent video windows are BD-J-only in the current implementation.'))
    if model.get('subtitles'):
        safe.append(_feature('hdmv_safe', 'subtitle_sidecars', 'Subtitle sidecars are title-muxing inputs, not a BD-J menu requirement.', hdmv_phase='v0.6'))

    report = {
        'schema_version': '1.0',
        'requested_backend_default': DEFAULT_MENU_BACKEND,
        'hdmv_compiler_status': HDMV_COMPILER_STATUS,
        'hdmv_compiler_functional': HDMV_COMPILER_STATUS in HDMV_FUNCTIONAL_COMPILER_STATUSES,
        'hdmv_safe': not bdj_required and not unsupported,
        'safe_features': safe,
        'bdj_required_features': bdj_required,
        'unsupported_features': unsupported,
        'summary': {
            'slides': len(slides),
            'buttons': len(buttons),
            'video_actions': len(video_actions),
            'slide_actions': len(slide_actions),
            'loop_videos': len(loop_videos),
        },
    }
    return report


def write_compatibility_report(menu_dir: Path, model: dict[str, Any], requested_backend: str | None = None, selected_backend: str | None = None) -> dict[str, Any]:
    report = analyze_menu_compatibility(model)
    if requested_backend:
        report['requested_backend'] = requested_backend
    if selected_backend:
        report['selected_backend'] = selected_backend
    (menu_dir / 'menu-compatibility.json').write_text(json.dumps(report, indent=2) + '\n')

    lines = [
        '# Menu backend compatibility report',
        '',
        f"Requested backend: `{requested_backend or '-'}`",
        f"Selected backend: `{selected_backend or '-'}`",
        f"HDMV-Lite compiler status: `{report['hdmv_compiler_status']}`",
        f"HDMV-safe: `{'yes' if report['hdmv_safe'] else 'no'}`",
        '',
        '## HDMV-safe features',
        '',
    ]
    for row in report['safe_features']:
        phase = f" ({row['hdmv_lite_phase']})" if row.get('hdmv_lite_phase') else ''
        lines.append(f"- `{row['feature']}`{phase}: {row['detail']}")
    if not report['safe_features']:
        lines.append('- none detected')
    lines += ['', '## Requires BD-J', '']
    for row in report['bdj_required_features']:
        lines.append(f"- `{row['feature']}`: {row['detail']}")
    if not report['bdj_required_features']:
        lines.append('- none detected')
    lines += ['', '## Unsupported by current scaffold', '']
    for row in report['unsupported_features']:
        lines.append(f"- `{row['feature']}`: {row['detail']}")
    if not report['unsupported_features']:
        lines.append('- none detected')
    (menu_dir / 'menu-compatibility.md').write_text('\n'.join(lines) + '\n')
    model['backend_compatibility'] = report
    model.setdefault('feature_requirements', report['safe_features'] + report['bdj_required_features'] + report['unsupported_features'])
    return report


def select_backend(requested: str, report: dict[str, Any]) -> str:
    requested = (requested or DEFAULT_MENU_BACKEND).lower()
    if requested not in MENU_BACKENDS:
        raise MenuBackendError(f'Unknown menu backend {requested!r}; choose one of: {", ".join(MENU_BACKENDS)}')
    if requested == 'auto':
        if report.get('hdmv_safe') and report.get('hdmv_compiler_status') in HDMV_FUNCTIONAL_COMPILER_STATUSES:
            return 'hdmv'
        return 'bdj'
    return requested


def convert_pptx_menu(root: Path, project: Path, *, requested_backend: str | None = None) -> tuple[Path, dict[str, Any], dict[str, Any], str]:
    """Run the neutral PPTX conversion once and attach a compatibility report."""
    menu_dir = root / 'xlets' / 'grin_samples' / 'Scripts' / 'PptxMenu'
    run([root / 'scripts' / 'convert-pptx-menu.sh', project])
    model = load_menu_model(menu_dir)
    report = write_compatibility_report(menu_dir, model, requested_backend=requested_backend)
    selected = select_backend(requested_backend or DEFAULT_MENU_BACKEND, report)
    report = write_compatibility_report(menu_dir, model, requested_backend=requested_backend or DEFAULT_MENU_BACKEND, selected_backend=selected)
    (menu_dir / 'menu-model.json').write_text(json.dumps(model, indent=2) + '\n')
    return menu_dir, model, report, selected


class BdjMenuBackend(MenuBackend):
    name = 'bdj'
    description = 'Current GRIN/BD-J backend using Java Xlet menu overlay.'

    def install(self, *, root: Path, project: Path, menu_dir: Path, disc_root: Path, output_root: Path, model: dict[str, Any]) -> dict[str, Any]:
        run(['ant', 'default'], cwd=menu_dir)
        jar_path = menu_dir / 'build' / '00000.jar'
        bdjo_path = menu_dir / 'build' / '00000.bdjo'
        if not jar_path.exists() or not bdjo_path.exists():
            raise MenuBackendError(f'PptxMenu build did not create expected {jar_path} and {bdjo_path}')

        bdmv = disc_root / 'BDMV'
        jar_dir = bdmv / 'JAR'
        bdjo_dir = bdmv / 'BDJO'
        aux_dir = bdmv / 'AUXDATA'
        cert_dir = disc_root / 'CERTIFICATE'

        shutil.rmtree(jar_dir, ignore_errors=True)
        shutil.rmtree(bdjo_dir, ignore_errors=True)
        jar_dir.mkdir(parents=True, exist_ok=True)
        bdjo_dir.mkdir(parents=True, exist_ok=True)
        aux_dir.mkdir(parents=True, exist_ok=True)
        cert_dir.mkdir(parents=True, exist_ok=True)
        (cert_dir / 'BACKUP').mkdir(parents=True, exist_ok=True)

        shutil.copy2(jar_path, jar_dir / '00000.jar')
        add_pptx_menu_assets_to_jar(menu_dir, jar_dir / '00000.jar')
        shutil.copy2(bdjo_path, bdjo_dir / '00000.bdjo')

        sample_font = root / 'xlets' / 'hdcookbook_discimage' / 'dist' / 'DiscImage' / 'BDMV' / 'AUXDATA' / '00000.otf'
        if sample_font.exists() and not (aux_dir / '00000.otf').exists():
            shutil.copy2(sample_font, aux_dir / '00000.otf')

        sign_pptx_menu_jar(root, disc_root, output_root)
        return {'backend': self.name, 'menu_dir': str(menu_dir), 'jar': str(jar_dir / '00000.jar'), 'bdjo': str(bdjo_dir / '00000.bdjo')}


def _slide_by_id(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(slide.get('id')): slide for slide in model.get('slides') or []}


def _button_hitbox(button: dict[str, Any]) -> dict[str, int] | None:
    hitbox = button.get('hitbox_px') or button.get('rect_px')
    if not isinstance(hitbox, dict):
        return None
    try:
        return {k: int(hitbox[k]) for k in ('x', 'y', 'w', 'h')}
    except (KeyError, TypeError, ValueError):
        return None


def _nearest_button(button: dict[str, Any], buttons: list[dict[str, Any]], direction: str) -> str:
    """Return a simple geometry-derived HDMV remote-neighbor target."""
    src = _button_hitbox(button)
    if not src:
        return str(button.get('id'))
    sx = src['x'] + src['w'] / 2
    sy = src['y'] + src['h'] / 2
    candidates = []
    for other in buttons:
        if other is button:
            continue
        dst = _button_hitbox(other)
        if not dst:
            continue
        ox = dst['x'] + dst['w'] / 2
        oy = dst['y'] + dst['h'] / 2
        dx = ox - sx
        dy = oy - sy
        if direction == 'left' and dx >= 0:
            continue
        if direction == 'right' and dx <= 0:
            continue
        if direction == 'up' and dy >= 0:
            continue
        if direction == 'down' and dy <= 0:
            continue
        primary = abs(dx) if direction in ('left', 'right') else abs(dy)
        secondary = abs(dy) if direction in ('left', 'right') else abs(dx)
        candidates.append((primary, secondary, str(other.get('id'))))
    return min(candidates)[2] if candidates else str(button.get('id'))


def _hdmv_lite_error(message: str, *, slide: str | None = None, button: str | None = None) -> dict[str, str]:
    row = {'message': message}
    if slide:
        row['slide'] = slide
    if button:
        row['button'] = button
    return row


def build_hdmv_lite_model(model: dict[str, Any], menu_dir: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Create a conservative HDMV-Lite IR and collect hard validation errors."""
    slides = model.get('slides') or []
    by_id = _slide_by_id(model)
    main_slide_id = str(slides[0].get('id')) if slides else None
    errors: list[dict[str, str]] = []
    hdmv_slides: list[dict[str, Any]] = []
    title_objects: dict[str, dict[str, Any]] = {}

    if not slides:
        errors.append(_hdmv_lite_error('HDMV-Lite requires at least one static menu slide.'))

    for slide_index, slide in enumerate(slides, 1):
        slide_id = str(slide.get('id') or f'slide{slide_index}')
        background = slide.get('background') or {}
        background_file = background.get('file')
        if background.get('kind') not in (None, 'static_image'):
            errors.append(_hdmv_lite_error('HDMV-Lite only supports static image backgrounds.', slide=slide_id))
        if not background_file:
            errors.append(_hdmv_lite_error('HDMV-Lite requires one rendered background image per menu page.', slide=slide_id))
        elif not (menu_dir / background_file).exists():
            errors.append(_hdmv_lite_error(f'Background asset is missing: {background_file}', slide=slide_id))

        if slide.get('loop_videos') or slide.get('menu_loop_video') or slide.get('menu_loop_action'):
            errors.append(_hdmv_lite_error('Motion/video-window menus are not supported by HDMV-Lite.', slide=slide_id))

        buttons = slide.get('buttons') or []
        if not buttons:
            errors.append(_hdmv_lite_error('HDMV-Lite menu pages require at least one button.', slide=slide_id))

        hdmv_buttons = []
        ordered_buttons = sorted(buttons, key=lambda b: int(b.get('focus_index') or 9999))
        for focus_index, button in enumerate(ordered_buttons, 1):
            button_id = str(button.get('id') or f'button{focus_index}')
            hitbox = _button_hitbox(button)
            if not hitbox or hitbox['w'] <= 0 or hitbox['h'] <= 0:
                errors.append(_hdmv_lite_error('Button is missing a valid rectangular pixel hitbox.', slide=slide_id, button=button_id))
                hitbox = {'x': 0, 'y': 0, 'w': 1, 'h': 1}
            if button.get('normal_overlay'):
                errors.append(_hdmv_lite_error('Button graphics over motion/video windows require BD-J today.', slide=slide_id, button=button_id))

            action = button.get('action') or {}
            kind = action.get('kind')
            if kind == 'video':
                playlist_id = str(action.get('playlist_id') or action.get('playlist') or '').zfill(5)
                title_number = action.get('title_number')
                if action.get('start_time_seconds') or action.get('chapter') or action.get('chapter_name') or action.get('chapter_number'):
                    errors.append(_hdmv_lite_error('Timestamp/chapter play-title actions are HDMV-Lite future work until final command compilation is implemented.', slide=slide_id, button=button_id))
                if not playlist_id or playlist_id == '00000' or not title_number:
                    errors.append(_hdmv_lite_error('Play-title actions require playlist_id and title_number.', slide=slide_id, button=button_id))
                target_key = playlist_id or str(title_number)
                title_objects[target_key] = {
                    'playlist_id': playlist_id,
                    'title_number': int(title_number or 0),
                    'video_file': action.get('video_file') or action.get('target'),
                }
                hdmv_action = {
                    'type': 'play_title',
                    'playlist_id': playlist_id,
                    'title_number': int(title_number or 0),
                }
            elif kind == 'slide':
                target = str(action.get('target') or action.get('menu_target') or '')
                if target not in by_id:
                    errors.append(_hdmv_lite_error(f'Go-to-menu action targets missing slide: {target}', slide=slide_id, button=button_id))
                hdmv_action = {
                    'type': 'return_main_menu' if target == main_slide_id else 'go_to_menu',
                    'target_menu': target,
                }
            elif kind == 'builtin':
                name = action.get('name') or action.get('type')
                if name in ('main', 'top_menu'):
                    hdmv_action = {'type': 'return_main_menu', 'target_menu': main_slide_id, 'builtin': name}
                elif name in ('disabled', 'none'):
                    hdmv_action = {'type': 'noop', 'builtin': name}
                elif name in ('back', 'play_all'):
                    errors.append(_hdmv_lite_error(f'Built-in action {name!r} is HDMV-Lite future work until final command compilation is implemented.', slide=slide_id, button=button_id))
                    hdmv_action = {'type': 'unsupported', 'builtin': name}
                else:
                    errors.append(_hdmv_lite_error(f'Built-in action {name!r} requires BD-J/runtime playback state in the current implementation.', slide=slide_id, button=button_id))
                    hdmv_action = {'type': 'unsupported', 'builtin': name}
            else:
                errors.append(_hdmv_lite_error(f'Unsupported HDMV-Lite action kind: {kind!r}', slide=slide_id, button=button_id))
                hdmv_action = {'type': 'unsupported', 'kind': kind}

            hdmv_buttons.append({
                'id': button_id,
                'label': button.get('label') or button_id,
                'select_value': focus_index,
                'hitbox_px': hitbox,
                'neighbors': {
                    'left': _nearest_button(button, buttons, 'left'),
                    'right': _nearest_button(button, buttons, 'right'),
                    'up': _nearest_button(button, buttons, 'up'),
                    'down': _nearest_button(button, buttons, 'down'),
                },
                'action': hdmv_action,
            })

        hdmv_slides.append({
            'id': slide_id,
            'page_id': slide_index,
            'title': slide.get('title') or slide_id,
            'background': {
                'file': background_file,
                'width': int(background.get('width') or 1920),
                'height': int(background.get('height') or 1080),
                'kind': 'static_image',
            },
            'buttons': hdmv_buttons,
        })

    title_rows = sorted(title_objects.values(), key=lambda r: (r.get('title_number') or 0, r.get('playlist_id') or ''))
    return {
        'schema_version': 'auto-bluray-hdmv-lite-v1',
        'backend': 'hdmv',
        'compiler_status': HDMV_COMPILER_STATUS,
        'capabilities': {
            'static_menu_pages': True,
            'single_background_image_per_page': True,
            'button_hitboxes': True,
            'actions': ['play_title', 'go_to_menu', 'return_main_menu'],
            'motion_video_windows': False,
            'java': False,
        },
        'entry_menu': main_slide_id,
        'menus': hdmv_slides,
        'titles': title_rows,
    }, errors


def build_hdmv_ig_plan(hdmv_model: dict[str, Any]) -> dict[str, Any]:
    """Export a lower-level, human-reviewable HDMV IG planning IR.

    This is still not a final binary Interactive Graphics compiler. It gives the
    project a stable intermediate representation for page/object/button layout so
    the next milestone can focus on binary encoding instead of re-deriving menu
    geometry from the frontend-neutral model each time.
    """
    pages: list[dict[str, Any]] = []
    objects: list[dict[str, Any]] = []

    for menu in hdmv_model.get('menus') or []:
        page_id = int(menu.get('page_id') or 0)
        menu_id = str(menu.get('id') or f'page{page_id}')
        background = menu.get('background') or {}
        bg_object_id = f'{menu_id}:bg'
        objects.append({
            'id': bg_object_id,
            'kind': 'background_bitmap',
            'menu_id': menu_id,
            'file': background.get('package_file') or background.get('file'),
            'width': int(background.get('width') or 1920),
            'height': int(background.get('height') or 1080),
        })

        buttons = []
        bogs = []
        for button_index, button in enumerate(menu.get('buttons') or [], 1):
            button_id = str(button.get('id') or f'button{button_index}')
            select_value = int(button.get('select_value') or button_index)
            bog_id = f'{menu_id}:bog:{select_value}'
            button_objects = button.get('object_refs') or {}
            buttons.append({
                'id': button_id,
                'bog_id': bog_id,
                'select_value': select_value,
                'label': button.get('label') or button_id,
                'hitbox_px': button.get('hitbox_px') or {},
                'neighbors': button.get('neighbors') or {},
                'action': button.get('action') or {},
                'visual_state_refs': {
                    'normal': bg_object_id,
                    'selected': button_objects.get('selected'),
                    'activated': button_objects.get('activated'),
                },
                'notes': [
                    'normal state reuses the page background bitmap in the planning IR',
                    'selected/activated states use generated per-button bitmap overlays',
                ],
            })
            bogs.append({
                'id': bog_id,
                'button_ids': [button_id],
                'auto_action': False,
                'notes': 'Single-button BOG placeholder; overlap grouping can be optimized later.',
            })

        pages.append({
            'page_id': page_id,
            'menu_id': menu_id,
            'title': menu.get('title') or menu_id,
            'background_object_id': bg_object_id,
            'default_selected_button_id': buttons[0]['id'] if buttons else None,
            'buttons': buttons,
            'bogs': bogs,
        })

    return {
        'schema_version': 'auto-bluray-hdmv-ig-plan-v1',
        'backend': 'hdmv',
        'entry_menu': hdmv_model.get('entry_menu'),
        'pages': pages,
        'objects': objects,
        'sound_effects': [],
        'notes': [
            'Planning IR only: this is not a compiled Interactive Graphics bitstream.',
            'Next milestone should encode this plan into final HDMV IG binary segments.',
        ],
    }


def compile_hdmv_ig_tables(ig_plan: dict[str, Any]) -> dict[str, Any]:
    """Normalize the planning IR into stable numbered tables for future binary encoding."""
    objects = list(ig_plan.get('objects') or [])
    object_index_by_id = {obj['id']: index for index, obj in enumerate(objects)}

    object_table = []
    for object_id in sorted(object_index_by_id, key=lambda oid: object_index_by_id[oid]):
        obj = next(o for o in objects if o['id'] == object_id)
        object_table.append({
            'object_index': object_index_by_id[object_id],
            'id': object_id,
            'kind': obj.get('kind'),
            'menu_id': obj.get('menu_id'),
            'button_id': obj.get('button_id'),
            'state': obj.get('state'),
            'file': obj.get('file'),
            'width': int(obj.get('width') or 0),
            'height': int(obj.get('height') or 0),
        })

    page_table = []
    button_table = []
    bog_table = []

    pages = list(ig_plan.get('pages') or [])
    for page_index, page in enumerate(pages):
        default_button_id = page.get('default_selected_button_id')
        page_table.append({
            'page_index': page_index,
            'page_id': int(page.get('page_id') or page_index),
            'menu_id': page.get('menu_id'),
            'title': page.get('title'),
            'background_object_index': object_index_by_id.get(page.get('background_object_id')),
            'default_selected_button_index': None,
        })

        local_button_index = {}
        for button_index, button in enumerate(page.get('buttons') or []):
            local_button_index[button['id']] = button_index
            refs = button.get('visual_state_refs') or {}
            button_table.append({
                'page_index': page_index,
                'button_index': button_index,
                'id': button.get('id'),
                'bog_id': button.get('bog_id'),
                'select_value': int(button.get('select_value') or (button_index + 1)),
                'label': button.get('label'),
                'hitbox_px': button.get('hitbox_px') or {},
                'neighbors': button.get('neighbors') or {},
                'normal_object_index': object_index_by_id.get(refs.get('normal')),
                'selected_object_index': object_index_by_id.get(refs.get('selected')),
                'activated_object_index': object_index_by_id.get(refs.get('activated')),
                'action': button.get('action') or {},
            })

        if default_button_id in local_button_index:
            page_table[-1]['default_selected_button_index'] = local_button_index[default_button_id]

        for bog_index, bog in enumerate(page.get('bogs') or []):
            bog_table.append({
                'page_index': page_index,
                'bog_index': bog_index,
                'id': bog.get('id'),
                'button_indexes': [local_button_index[button_id] for button_id in bog.get('button_ids') or [] if button_id in local_button_index],
                'auto_action': bool(bog.get('auto_action')),
            })

    return {
        'schema_version': 'auto-bluray-hdmv-ig-tables-v1',
        'entry_menu': ig_plan.get('entry_menu'),
        'object_table': object_table,
        'page_table': page_table,
        'button_table': button_table,
        'bog_table': bog_table,
        'sound_effect_table': [],
    }


def compile_hdmv_ig_assembly(ig_tables: dict[str, Any]) -> dict[str, Any]:
    """Build a serializer-shaped IG assembly export with reference validation."""
    object_table = list(ig_tables.get('object_table') or [])
    page_table = list(ig_tables.get('page_table') or [])
    button_table = list(ig_tables.get('button_table') or [])
    bog_table = list(ig_tables.get('bog_table') or [])

    object_indexes = {row.get('object_index') for row in object_table}
    object_rows_by_index = {row.get('object_index'): row for row in object_table}
    button_keys = {(row.get('page_index'), row.get('button_index')) for row in button_table}
    errors: list[dict[str, Any]] = []

    def require_object(ref: int | None, *, context: str, allow_none: bool = False):
        if ref is None:
            if not allow_none:
                errors.append({'type': 'missing_object_ref', 'context': context})
            return
        if ref not in object_indexes:
            errors.append({'type': 'invalid_object_ref', 'context': context, 'object_index': ref})

    def require_range(value: int | None, *, min_value: int, max_value: int, error_type: str, context: str):
        if value is None:
            errors.append({'type': error_type, 'context': context, 'value': value, 'min': min_value, 'max': max_value})
            return
        if not (min_value <= int(value) <= max_value):
            errors.append({'type': error_type, 'context': context, 'value': int(value), 'min': min_value, 'max': max_value})

    action_records: list[dict[str, Any]] = []
    action_index_by_key: dict[tuple[Any, ...], int] = {}

    def intern_action(action: dict[str, Any]) -> int:
        action_type = str(action.get('type') or 'noop')
        key = (
            action_type,
            action.get('playlist_id'),
            action.get('title_number'),
            action.get('target_menu'),
            action.get('builtin'),
        )
        if key in action_index_by_key:
            return action_index_by_key[key]
        opcode_map = {
            'noop': 'NOP',
            'play_title': 'JUMP_TITLE',
            'go_to_menu': 'SET_BUTTON_PAGE',
            'return_main_menu': 'SET_BUTTON_PAGE',
        }
        record = {
            'action_index': len(action_records),
            'type': action_type,
            'opcode': opcode_map.get(action_type, 'UNSUPPORTED'),
            'playlist_id': action.get('playlist_id'),
            'title_number': action.get('title_number'),
            'target_menu': action.get('target_menu'),
            'target_page_index': None,
            'builtin': action.get('builtin'),
        }
        action_index_by_key[key] = record['action_index']
        action_records.append(record)
        return record['action_index']

    page_assemblies = []
    for page in page_table:
        page_index = int(page.get('page_index') or 0)
        require_range(page.get('page_id'), min_value=0, max_value=0xFE, error_type='page_id_out_of_range', context=f'page[{page_index}].page_id')
        require_object(page.get('background_object_index'), context=f'page[{page_index}].background')
        page_buttons = [row for row in button_table if row.get('page_index') == page_index]
        page_bogs = [row for row in bog_table if row.get('page_index') == page_index]

        background_object_index = page.get('background_object_index')
        background_object = object_rows_by_index.get(background_object_index)
        if background_object:
            if background_object.get('kind') != 'background_bitmap':
                errors.append({
                    'type': 'invalid_background_object_kind',
                    'page_index': page_index,
                    'object_index': background_object_index,
                    'kind': background_object.get('kind'),
                })
            if background_object.get('menu_id') != page.get('menu_id'):
                errors.append({
                    'type': 'background_menu_mismatch',
                    'page_index': page_index,
                    'object_index': background_object_index,
                    'expected_menu_id': page.get('menu_id'),
                    'actual_menu_id': background_object.get('menu_id'),
                })

        default_button_index = page.get('default_selected_button_index')
        if default_button_index is not None and (page_index, default_button_index) not in button_keys:
            errors.append({'type': 'invalid_default_button', 'page_index': page_index, 'button_index': default_button_index})

        button_assemblies = []
        for button in page_buttons:
            button_index = int(button.get('button_index') or 0)
            require_range(button.get('select_value'), min_value=1, max_value=0xFFFF, error_type='select_value_out_of_range', context=f'page[{page_index}].button[{button_index}].select_value')
            for state_name in ('normal_object_index', 'selected_object_index', 'activated_object_index'):
                require_object(button.get(state_name), context=f'page[{page_index}].button[{button_index}].{state_name}', allow_none=(state_name != 'normal_object_index'))

            neighbors = button.get('neighbors') or {}
            neighbor_indexes = {}
            by_id = {row.get('id'): row.get('button_index') for row in page_buttons}
            for direction, target_id in neighbors.items():
                if target_id not in by_id:
                    errors.append({'type': 'invalid_neighbor', 'page_index': page_index, 'button_index': button_index, 'direction': direction, 'target_id': target_id})
                    continue
                neighbor_indexes[direction] = by_id[target_id]

            hitbox = button.get('hitbox_px') or {}
            expected_width = int(hitbox.get('w') or 0)
            expected_height = int(hitbox.get('h') or 0)
            for state_name, object_index in (
                ('selected', button.get('selected_object_index')),
                ('activated', button.get('activated_object_index')),
            ):
                if object_index is None:
                    continue
                obj = object_rows_by_index.get(object_index)
                if not obj:
                    continue
                if obj.get('kind') != 'button_state_bitmap':
                    errors.append({
                        'type': 'invalid_button_state_object_kind',
                        'page_index': page_index,
                        'button_index': button_index,
                        'state': state_name,
                        'object_index': object_index,
                        'kind': obj.get('kind'),
                    })
                if obj.get('menu_id') != page.get('menu_id') or obj.get('button_id') != button.get('id') or obj.get('state') != state_name:
                    errors.append({
                        'type': 'button_state_object_identity_mismatch',
                        'page_index': page_index,
                        'button_index': button_index,
                        'state': state_name,
                        'object_index': object_index,
                        'expected_menu_id': page.get('menu_id'),
                        'actual_menu_id': obj.get('menu_id'),
                        'expected_button_id': button.get('id'),
                        'actual_button_id': obj.get('button_id'),
                        'expected_state': state_name,
                        'actual_state': obj.get('state'),
                    })
                actual_width = int(obj.get('width') or 0)
                actual_height = int(obj.get('height') or 0)
                if actual_width != expected_width or actual_height != expected_height:
                    errors.append({
                        'type': 'button_state_dimension_mismatch',
                        'page_index': page_index,
                        'button_index': button_index,
                        'state': state_name,
                        'object_index': object_index,
                        'expected_width': expected_width,
                        'expected_height': expected_height,
                        'actual_width': actual_width,
                        'actual_height': actual_height,
                    })

            button_assemblies.append({
                'button_index': button_index,
                'select_value': int(button.get('select_value') or 0),
                'bog_id': button.get('bog_id'),
                'action_index': intern_action(button.get('action') or {}),
                'object_indexes': {
                    'normal': button.get('normal_object_index'),
                    'selected': button.get('selected_object_index'),
                    'activated': button.get('activated_object_index'),
                },
                'neighbor_button_indexes': neighbor_indexes,
                'action': button.get('action') or {},
            })

        bog_assemblies = []
        for bog in page_bogs:
            button_indexes = [int(idx) for idx in bog.get('button_indexes') or []]
            if len(button_indexes) > 0xFF:
                errors.append({'type': 'bog_button_count_out_of_range', 'page_index': page_index, 'bog_index': bog.get('bog_index'), 'count': len(button_indexes), 'max': 0xFF})
            for idx in button_indexes:
                if (page_index, idx) not in button_keys:
                    errors.append({'type': 'invalid_bog_button', 'page_index': page_index, 'bog_index': bog.get('bog_index'), 'button_index': idx})
            bog_assemblies.append({
                'bog_index': int(bog.get('bog_index') or 0),
                'button_indexes': button_indexes,
                'auto_action': bool(bog.get('auto_action')),
            })

        page_assemblies.append({
            'page_index': page_index,
            'page_id': int(page.get('page_id') or 0),
            'background_object_index': page.get('background_object_index'),
            'default_selected_button_index': default_button_index,
            'buttons': button_assemblies,
            'bogs': bog_assemblies,
        })

    entry_menu = ig_tables.get('entry_menu')
    entry_page_index = None
    menu_name_to_page_index = {}
    for page in page_table:
        menu_name_to_page_index[page.get('menu_id')] = page.get('page_index')
        if page.get('menu_id') == entry_menu:
            entry_page_index = page.get('page_index')
    if entry_menu is not None and entry_page_index is None:
        errors.append({'type': 'invalid_entry_menu', 'entry_menu': entry_menu})

    for row in action_records:
        target_menu = row.get('target_menu')
        if target_menu in (None, ''):
            continue
        target_page_index = menu_name_to_page_index.get(target_menu)
        if target_page_index is None:
            errors.append({'type': 'invalid_action_target_menu', 'action_index': row.get('action_index'), 'target_menu': target_menu})
            continue
        row['target_page_index'] = target_page_index

    return {
        'schema_version': 'auto-bluray-hdmv-ig-assembly-v1',
        'entry_menu': entry_menu,
        'entry_page_index': entry_page_index,
        'object_count': len(object_table),
        'page_count': len(page_table),
        'action_count': len(action_records),
        'action_table': action_records,
        'pages': page_assemblies,
        'validation': {
            'ok': not errors,
            'errors': errors,
        },
    }


def _pack_u8(value: int) -> bytes:
    return int(value).to_bytes(1, 'big', signed=False)


def _pack_u16(value: int) -> bytes:
    return int(value).to_bytes(2, 'big', signed=False)


def _pack_u32(value: int) -> bytes:
    return int(value).to_bytes(4, 'big', signed=False)


def _pack_optional_u16(value: int | None) -> int:
    return 0xFFFF if value is None else int(value)


def pack_hdmv_ig_binary_scaffold(ig_assembly: dict[str, Any]) -> dict[str, Any]:
    """Pack the validated IG assembly into deterministic byte-oriented scaffold sections.

    This is intentionally not a final Blu-ray IG encoder. It provides stable
    section payloads, offsets, and hashes so later binary work can focus on the
    real HDMV field semantics instead of basic record ordering/packing.
    """
    validation = ig_assembly.get('validation') or {}
    if not validation.get('ok'):
        raise MenuBackendError('Cannot pack HDMV IG binary scaffold: assembly validation failed.')

    pages = list(ig_assembly.get('pages') or [])
    actions = sorted(ig_assembly.get('action_table') or [], key=lambda row: int(row.get('action_index') or 0))

    if len(pages) > 0xFFFF:
        raise MenuBackendError('Cannot pack HDMV IG binary scaffold: too many pages for scaffold field widths.')
    if int(ig_assembly.get('object_count') or 0) > 0xFFFF:
        raise MenuBackendError('Cannot pack HDMV IG binary scaffold: too many objects for scaffold field widths.')
    if len(actions) > 0xFFFF:
        raise MenuBackendError('Cannot pack HDMV IG binary scaffold: too many actions for scaffold field widths.')

    header = bytearray()
    header.extend(b'IGSC')
    header.extend(_pack_u16(1))
    header.extend(_pack_u16(int(ig_assembly.get('entry_page_index') or 0)))
    header.extend(_pack_u16(int(ig_assembly.get('page_count') or len(pages))))
    header.extend(_pack_u16(int(ig_assembly.get('object_count') or 0)))
    header.extend(_pack_u16(int(ig_assembly.get('action_count') or len(actions))))

    page_records = bytearray()
    button_records = bytearray()
    bog_records = bytearray()
    action_records = bytearray()

    opcode_map = {
        'NOP': 0,
        'JUMP_TITLE': 1,
        'SET_BUTTON_PAGE': 2,
        'UNSUPPORTED': 255,
    }

    for action in actions:
        action_records.extend(_pack_u16(int(action.get('action_index') or 0)))
        action_records.extend(_pack_u8(opcode_map.get(action.get('opcode'), 255)))
        action_records.extend(_pack_u8(0))
        action_records.extend(_pack_u16(int(action.get('title_number') or 0)))
        playlist_num = 0
        playlist_id = action.get('playlist_id')
        if playlist_id not in (None, ''):
            try:
                playlist_num = int(str(playlist_id))
            except ValueError:
                playlist_num = 0
        action_records.extend(_pack_u16(playlist_num))
        target_page_index = action.get('target_page_index')
        action_records.extend(_pack_u16(_pack_optional_u16(target_page_index)))

    for page in sorted(pages, key=lambda row: int(row.get('page_index') or 0)):
        page_index = int(page.get('page_index') or 0)
        buttons = sorted(page.get('buttons') or [], key=lambda row: int(row.get('button_index') or 0))
        bogs = sorted(page.get('bogs') or [], key=lambda row: int(row.get('bog_index') or 0))
        if len(buttons) > 0xFFFF or len(bogs) > 0xFFFF:
            raise MenuBackendError(f'Cannot pack HDMV IG binary scaffold: page {page_index} exceeds scaffold count limits.')
        # Public HDMV IG page semantics expose at least a page id, animation
        # frame-rate behavior, and per-page background behavior. We still use a
        # conservative static-page profile here, but the record now reserves
        # explicit page-level slots for those semantics instead of only packing
        # counts and object refs.
        animation_frame_rate_code = int(page.get('animation_frame_rate_code') or 0)
        background_behavior_code = int(page.get('background_behavior_code') or 1)
        page_records.extend(_pack_u16(page_index))
        page_records.extend(_pack_u16(int(page.get('page_id') or 0)))
        page_records.extend(_pack_u8(animation_frame_rate_code))
        page_records.extend(_pack_u8(background_behavior_code))
        page_records.extend(_pack_u16(int(page.get('background_object_index') or 0)))
        page_records.extend(_pack_u16(_pack_optional_u16(page.get('default_selected_button_index'))))
        page_records.extend(_pack_u16(len(buttons)))
        page_records.extend(_pack_u16(len(bogs)))

        for button in buttons:
            neighbors = button.get('neighbor_button_indexes') or {}
            object_indexes = button.get('object_indexes') or {}
            normal_object_index = int(object_indexes.get('normal') or 0)
            selected_object_index = _pack_optional_u16(object_indexes.get('selected'))
            activated_object_index = _pack_optional_u16(object_indexes.get('activated'))
            button_records.extend(_pack_u16(page_index))
            button_records.extend(_pack_u16(int(button.get('button_index') or 0)))
            button_records.extend(_pack_u16(int(button.get('select_value') or 0)))
            button_records.extend(_pack_u16(_pack_optional_u16(neighbors.get('left'))))
            button_records.extend(_pack_u16(_pack_optional_u16(neighbors.get('right'))))
            button_records.extend(_pack_u16(_pack_optional_u16(neighbors.get('up'))))
            button_records.extend(_pack_u16(_pack_optional_u16(neighbors.get('down'))))
            # Public HDMV IG authoring docs describe button states using start/end
            # object references plus repeat flags, with optional selected/
            # activated sound refs. We still emit a conservative static-only
            # form, but the record layout now mirrors that public state model
            # instead of a single opaque object ref per state.
            button_records.extend(_pack_u16(normal_object_index))
            button_records.extend(_pack_u16(normal_object_index))
            button_records.extend(_pack_u8(0))
            button_records.extend(_pack_u8(0xFF))
            button_records.extend(_pack_u16(selected_object_index))
            button_records.extend(_pack_u16(selected_object_index))
            button_records.extend(_pack_u8(0))
            button_records.extend(_pack_u8(0xFF))
            button_records.extend(_pack_u16(activated_object_index))
            button_records.extend(_pack_u16(activated_object_index))
            button_records.extend(_pack_u8(0))
            button_records.extend(_pack_u8(0xFF))
            button_records.extend(_pack_u16(int(button.get('action_index') or 0)))

        for bog in bogs:
            bog_buttons = [int(idx) for idx in bog.get('button_indexes') or []]
            if len(bog_buttons) > 0xFF:
                raise MenuBackendError(f'Cannot pack HDMV IG binary scaffold: BOG on page {page_index} exceeds scaffold button count limit.')
            bog_records.extend(_pack_u16(page_index))
            bog_records.extend(_pack_u16(int(bog.get('bog_index') or 0)))
            bog_records.extend(_pack_u8(1 if bog.get('auto_action') else 0))
            bog_records.extend(_pack_u8(len(bog_buttons)))
            for idx in bog_buttons:
                bog_records.extend(_pack_u16(idx))

    sections = []
    offset = 0
    section_layouts = {
        'header': 'magic,u16 version,u16 entry_page_index,u16 page_count,u16 object_count,u16 action_count',
        'pages': 'repeated: u16 page_index,u16 page_id,u8 animation_frame_rate_code,u8 background_behavior_code,u16 background_object_index,u16 default_selected_button_index,u16 button_count,u16 bog_count',
        'buttons': 'repeated: u16 page_index,u16 button_index,u16 select_value,u16 left,u16 right,u16 up,u16 down,(u16 start,u16 end,u8 repeat,u8 sound)*3 states,u16 action_index',
        'bogs': 'repeated: u16 page_index,u16 bog_index,u8 auto_action,u8 button_count,button_count*u16 button_index',
        'actions': 'repeated: u16 action_index,u8 opcode,u8 reserved,u16 title_number,u16 playlist_num,u16 target_page_index',
    }
    for name, payload in (
        ('header', bytes(header)),
        ('pages', bytes(page_records)),
        ('buttons', bytes(button_records)),
        ('bogs', bytes(bog_records)),
        ('actions', bytes(action_records)),
    ):
        sections.append({
            'name': name,
            'offset': offset,
            'size': len(payload),
            'hex': payload.hex(),
            'record_layout': section_layouts.get(name),
        })
        offset += len(payload)

    return {
        'schema_version': 'auto-bluray-hdmv-ig-binary-scaffold-v1',
        'entry_page_index': ig_assembly.get('entry_page_index'),
        'total_size': offset,
        'sections': sections,
        'notes': [
            'Deterministic byte-oriented scaffold only; not a final HDMV IG bitstream.',
            'Button records now mirror the public IG authoring model more closely by encoding per-state start/end refs plus repeat/sound slots in a static-only form.',
            'Page records now carry explicit animation-frame-rate and background-behavior slots using a conservative static-page profile.',
            'Next milestone should replace the remaining placeholder record layouts with real HDMV IG binary field semantics.',
        ],
    }


def materialize_hdmv_ig_binary_scaffold(ig_binary: dict[str, Any]) -> bytes:
    """Concatenate scaffold sections into a single byte blob for inspection/tests."""
    payload = bytearray()
    expected_offset = 0
    for section in ig_binary.get('sections') or []:
        offset = int(section.get('offset') or 0)
        if offset != expected_offset:
            raise MenuBackendError(
                f'Cannot materialize HDMV IG binary scaffold: section {section.get("name")!r} '
                f'expected offset {expected_offset}, got {offset}.'
            )
        chunk = bytes.fromhex(section.get('hex') or '')
        declared_size = int(section.get('size') or 0)
        if len(chunk) != declared_size:
            raise MenuBackendError(
                f'Cannot materialize HDMV IG binary scaffold: section {section.get("name")!r} '
                f'declared {declared_size} bytes but hex decodes to {len(chunk)}.'
            )
        payload.extend(chunk)
        expected_offset += len(chunk)
    if len(payload) != int(ig_binary.get('total_size') or 0):
        raise MenuBackendError(
            f'Cannot materialize HDMV IG binary scaffold: total_size={ig_binary.get("total_size")} '
            f'but materialized {len(payload)} bytes.'
        )
    return bytes(payload)


def compile_hdmv_ig_packet_container(ig_binary: dict[str, Any]) -> dict[str, Any]:
    """Wrap scaffold sections in a deterministic packet/container structure.

    This is still not a final Blu-ray Interactive Graphics stream. It provides
    a concrete packet directory and payload framing layer so later work can swap
    in real HDMV segment types without revisiting package-level plumbing.
    """
    packets = []
    type_map = {
        'header': 1,
        'pages': 2,
        'buttons': 3,
        'bogs': 4,
        'actions': 5,
    }
    payload_offset = 0
    for index, section in enumerate(ig_binary.get('sections') or []):
        size = int(section.get('size') or 0)
        packets.append({
            'packet_index': index,
            'packet_type': type_map.get(section.get('name'), 255),
            'section_name': section.get('name'),
            'payload_offset': payload_offset,
            'payload_size': size,
            'hex': section.get('hex') or '',
        })
        payload_offset += size

    return {
        'schema_version': 'auto-bluray-hdmv-ig-packet-container-v1',
        'source_schema_version': ig_binary.get('schema_version'),
        'entry_page_index': ig_binary.get('entry_page_index'),
        'packet_count': len(packets),
        'payload_size': payload_offset,
        'packets': packets,
        'notes': [
            'Packet/container scaffold only; not a final Blu-ray IGS transport stream.',
            'Later milestones should replace these generic packet headers with real HDMV segment/container encoding.',
        ],
    }


def materialize_hdmv_ig_packet_container(container: dict[str, Any]) -> bytes:
    """Serialize the packet/container scaffold into a deterministic binary blob."""
    packets = list(container.get('packets') or [])
    header = bytearray()
    header.extend(b'IGPK')
    header.extend(_pack_u16(1))
    header.extend(_pack_u16(int(container.get('packet_count') or len(packets))))
    header.extend(_pack_u16(int(container.get('entry_page_index') or 0)))
    header.extend(_pack_u32(int(container.get('payload_size') or 0)))

    directory = bytearray()
    payload = bytearray()
    expected_payload_offset = 0
    for packet in packets:
        payload_offset = int(packet.get('payload_offset') or 0)
        if payload_offset != expected_payload_offset:
            raise MenuBackendError(
                f'Cannot materialize HDMV IG packet container: packet {packet.get("packet_index")} '
                f'expected payload offset {expected_payload_offset}, got {payload_offset}.'
            )
        chunk = bytes.fromhex(packet.get('hex') or '')
        payload_size = int(packet.get('payload_size') or 0)
        if len(chunk) != payload_size:
            raise MenuBackendError(
                f'Cannot materialize HDMV IG packet container: packet {packet.get("packet_index")} '
                f'declared {payload_size} bytes but hex decodes to {len(chunk)}.'
            )
        directory.extend(_pack_u16(int(packet.get('packet_index') or 0)))
        directory.extend(_pack_u8(int(packet.get('packet_type') or 255)))
        directory.extend(_pack_u8(0))
        directory.extend(_pack_u32(payload_offset))
        directory.extend(_pack_u32(payload_size))
        payload.extend(chunk)
        expected_payload_offset += len(chunk)

    if len(payload) != int(container.get('payload_size') or 0):
        raise MenuBackendError(
            f'Cannot materialize HDMV IG packet container: payload_size={container.get("payload_size")} '
            f'but materialized {len(payload)} bytes.'
        )

    return bytes(header + directory + payload)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _render_button_state_overlay(background_path: Path, hitbox: dict[str, int], *, outline_rgba: tuple[int, int, int, int], fill_rgba: tuple[int, int, int, int]) -> Image.Image:
    background = Image.open(background_path).convert('RGBA')
    bg_w, bg_h = background.size
    x = _clamp(int(hitbox.get('x', 0)), 0, max(bg_w - 1, 0))
    y = _clamp(int(hitbox.get('y', 0)), 0, max(bg_h - 1, 0))
    w = max(1, int(hitbox.get('w', 1)))
    h = max(1, int(hitbox.get('h', 1)))
    x2 = _clamp(x + w, x + 1, bg_w)
    y2 = _clamp(y + h, y + 1, bg_h)
    crop = background.crop((x, y, x2, y2)).copy()

    overlay = Image.new('RGBA', crop.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    max_x = max(crop.size[0] - 1, 0)
    max_y = max(crop.size[1] - 1, 0)
    radius = max(4, min(crop.size) // 8)
    border = max(2, min(crop.size) // 18)
    draw.rounded_rectangle((0, 0, max_x, max_y), radius=radius, fill=fill_rgba, outline=outline_rgba, width=border)
    return Image.alpha_composite(crop, overlay)


def generate_hdmv_button_state_assets(hdmv_model: dict[str, Any], package_dir: Path) -> None:
    for menu in hdmv_model.get('menus') or []:
        background = menu.get('background') or {}
        background_file = background.get('package_file') or background.get('file')
        if not background_file:
            continue
        background_path = package_dir / background_file
        if not background_path.exists():
            continue
        menu_id = str(menu.get('id') or f'page{menu.get("page_id") or 0}')
        for button in menu.get('buttons') or []:
            button_id = str(button.get('id') or 'button')
            hitbox = button.get('hitbox_px') or {}
            selected_rel = Path('assets') / f'{menu_id}_{button_id}_selected.png'
            activated_rel = Path('assets') / f'{menu_id}_{button_id}_activated.png'
            selected_path = package_dir / selected_rel
            activated_path = package_dir / activated_rel
            selected_path.parent.mkdir(parents=True, exist_ok=True)

            _render_button_state_overlay(
                background_path,
                hitbox,
                outline_rgba=(255, 215, 0, 255),
                fill_rgba=(255, 215, 0, 70),
            ).save(selected_path)
            _render_button_state_overlay(
                background_path,
                hitbox,
                outline_rgba=(255, 140, 0, 255),
                fill_rgba=(255, 140, 0, 120),
            ).save(activated_path)

            button['object_refs'] = {
                'selected': f'{menu_id}:{button_id}:selected',
                'activated': f'{menu_id}:{button_id}:activated',
            }
            button['state_assets'] = {
                'selected': str(selected_rel),
                'activated': str(activated_rel),
            }


def _write_hdmv_lite_index_xml(path: Path, title_count: int):
    title_entries = []
    for i in range(title_count):
        mobj_id = i + 2
        title_entries.append(f"""            <title>
                <indexObject xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:type=\"HDMVIndexObject\">
                    <HDMVName>0x{mobj_id:x}</HDMVName>
                    <playbackType>HDMVPlayback_MOVIE</playbackType>
                </indexObject>
                <titleAccessType>V_00</titleAccessType>
            </title>""")
    path.write_text(f"""<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<index>
    <appInfo/>
    <extensionData/>
    <indexes>
        <firstPlayback>
            <firstPlaybackObject xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:type=\"HDMVIndexObject\">
                <HDMVName>0x0</HDMVName>
                <playbackType>HDMVPlayback_MOVIE</playbackType>
            </firstPlaybackObject>
        </firstPlayback>
        <topMenu>
            <topMenuObject xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:type=\"HDMVIndexObject\">
                <HDMVName>0x1</HDMVName>
                <playbackType>HDMVPlayback_INTERACTIVE</playbackType>
            </topMenuObject>
        </topMenu>
        <titles>
{chr(10).join(title_entries)}
        </titles>
    </indexes>
    <paddingN1>0</paddingN1>
    <paddingN2>0</paddingN2>
    <paddingN3>0</paddingN3>
    <version>0200</version>
</index>
""", encoding='utf-8')


def compile_hdmv_movieobject_plan(hdmv_model: dict[str, Any]) -> dict[str, Any]:
    """Build a conservative MovieObject graph plus sample-backed command fallback.

    Local HD Cook Book samples use `21810000 <title> 00000000` for Jump Title.
    We reuse that public/sample-backed pattern for title-launch objects while
    adding an explicit object graph for menu/page flow so the next compiler
    milestone can replace fallback commands with real JumpObject/SetButtonPage
    bytecode instead of reconstructing dispatch intent from scratch.
    """
    titles = list(hdmv_model.get('titles') or [])
    menus = list(hdmv_model.get('menus') or [])
    jump_title_opcode = '21810000'
    objects = []
    routes = []

    default_title_number = int((titles[0] or {}).get('title_number') or 1) if titles else 1
    default_command = f'{jump_title_opcode} {default_title_number:08x} 00000000'
    title_object_ids: dict[int, int] = {}
    menu_object_ids: dict[str, int] = {}

    next_menu_object_id = len(titles) + 2
    for menu in menus:
        menu_id = str(menu.get('id') or f'page{len(menu_object_ids)}')
        menu_object_ids[menu_id] = next_menu_object_id
        next_menu_object_id += 1

    objects.append({
        'mobj_id': 0,
        'kind': 'first_playback',
        'intended_target_mobj_id': 1 if menus else (2 if titles else None),
        'target_title_number': default_title_number,
        'intended_commands': [
            {
                'op': 'JumpObject' if menus else 'JumpTitle',
                'target_mobj_id': 1 if menus else None,
                'target_title_number': None if menus else default_title_number,
                'notes': 'Desired first-playback dispatch to the interactive top-menu object when menu command compilation is available.',
            }
        ],
        'commands': [default_command],
        'fallback_mode': 'sample_jump_title',
        'notes': 'First-playback intends to jump into the top-menu object graph; actual bytes still use a sample-backed JumpTitle fallback until real JumpObject compilation exists.',
    })
    objects.append({
        'mobj_id': 1,
        'kind': 'top_menu',
        'entry_menu': hdmv_model.get('entry_menu'),
        'target_menu': hdmv_model.get('entry_menu'),
        'target_page_id': next((int(menu.get('page_id') or 0) for menu in menus if menu.get('id') == hdmv_model.get('entry_menu')), None),
        'intended_target_mobj_id': menu_object_ids.get(str(hdmv_model.get('entry_menu'))) if hdmv_model.get('entry_menu') is not None else None,
        'intended_commands': [
            {
                'op': 'JumpObject' if hdmv_model.get('entry_menu') in menu_object_ids else 'JumpTitle',
                'target_mobj_id': menu_object_ids.get(str(hdmv_model.get('entry_menu'))) if hdmv_model.get('entry_menu') is not None else None,
                'target_menu': hdmv_model.get('entry_menu'),
                'target_page_id': next((int(menu.get('page_id') or 0) for menu in menus if menu.get('id') == hdmv_model.get('entry_menu')), None),
                'notes': 'Desired Top Menu dispatch into the entry menu page object when menu command compilation is available.',
            }
        ],
        'target_title_number': default_title_number,
        'commands': [default_command],
        'fallback_mode': 'sample_jump_title',
        'notes': 'Top Menu intends to jump into the entry menu page object; actual bytes still use a sample-backed JumpTitle fallback until SetButtonPage/JumpObject compilation exists.',
    })

    for title in titles:
        title_number = int(title.get('title_number') or 0)
        mobj_id = title_number + 1
        title_object_ids[title_number] = mobj_id
        command = f'{jump_title_opcode} {title_number:08x} 00000000'
        objects.append({
            'mobj_id': mobj_id,
            'kind': 'jump_title',
            'target_title_number': title_number,
            'playlist_id': title.get('playlist_id'),
            'video_file': title.get('video_file'),
            'intended_commands': [
                {
                    'op': 'JumpTitle',
                    'target_title_number': title_number,
                    'playlist_id': title.get('playlist_id'),
                }
            ],
            'commands': [command],
            'fallback_mode': 'sample_jump_title',
            'notes': 'Sample-backed JumpTitle command derived from local HD Cook Book MovieObject.xml.',
        })

    for menu in menus:
        menu_id = str(menu.get('id') or f'page{len(menu_object_ids)}')
        page_id = int(menu.get('page_id') or 0)
        button_routes = []
        for button in menu.get('buttons') or []:
            action = button.get('action') or {}
            action_type = str(action.get('type') or 'noop')
            route = {
                'button_id': button.get('id'),
                'label': button.get('label'),
                'action_type': action_type,
            }
            if action_type == 'play_title':
                title_number = int(action.get('title_number') or 0)
                route.update({
                    'op': 'JumpTitle',
                    'target_title_number': title_number,
                    'target_mobj_id': title_object_ids.get(title_number),
                    'playlist_id': action.get('playlist_id'),
                })
            elif action_type in {'go_to_menu', 'return_main_menu'}:
                target_menu = str(action.get('target_menu') or action.get('target') or hdmv_model.get('entry_menu') or menu_id)
                target_page_id = next((int(row.get('page_id') or 0) for row in menus if str(row.get('id')) == target_menu), None)
                route.update({
                    'op': 'SetButtonPage',
                    'target_menu': target_menu,
                    'target_page_id': target_page_id,
                    'target_mobj_id': menu_object_ids.get(target_menu),
                })
            else:
                route.update({'op': 'Nop'})
            button_routes.append(route)
            routes.append({'menu_id': menu_id, **route})

        objects.append({
            'mobj_id': menu_object_ids[menu_id],
            'kind': 'menu_page',
            'menu_id': menu_id,
            'title': menu.get('title') or menu_id,
            'page_id': page_id,
            'button_routes': button_routes,
            'intended_commands': [
                {
                    'op': 'SetButtonPage',
                    'target_page_id': page_id,
                    'target_menu': menu_id,
                }
            ],
            'commands': [default_command],
            'fallback_mode': 'sample_jump_title',
            'notes': 'Menu page object graph is now modeled explicitly, but still falls back to a sample-backed JumpTitle word until real page-display command compilation exists.',
        })

    return {
        'schema_version': 'auto-bluray-hdmv-movieobject-plan-v1',
        'command_source': 'local-hdcookbook-sample',
        'compiler_status': 'graph_planned_sample_title_fallback',
        'entry_menu': hdmv_model.get('entry_menu'),
        'menu_object_ids': menu_object_ids,
        'title_object_ids': title_object_ids,
        'routes': routes,
        'objects': objects,
    }


def compile_hdmv_movieobject_commands(
    movieobject_plan: dict[str, Any],
    *,
    opcode_registry: dict[str, HdmvOpcodeSpec] | None = None,
) -> dict[str, Any]:
    """Compile planned MovieObject ops into command words where known.

    Today only JumpTitle has a sample-backed public word pattern we trust enough
    to emit directly. Menu/navigation ops still compile in *fallback* mode: we
    preserve the intended op and target metadata, but emit a safe JumpTitle word
    so the XML/binary toolchain keeps producing output without inventing opaque
    undocumented bytes for JumpObject/SetButtonPage yet.
    """
    registry = opcode_registry or HDMV_MOVIEOBJECT_OPCODE_REGISTRY
    compiled_objects = []
    unsupported_ops: dict[str, int] = {}
    native_ops: dict[str, int] = {}

    for row in movieobject_plan.get('objects') or []:
        compiled_rows = []
        compiled_words = []
        for command_index, intended in enumerate(row.get('intended_commands') or []):
            op = str(intended.get('op') or 'Nop')
            spec = registry.get(op)
            compiled = {
                'command_index': command_index,
                'op': op,
                'status': 'planned',
                'word': None,
                'fallback': None,
                'registry_mode': spec.mode if spec else 'unregistered',
            }
            if spec and spec.mode == 'native' and spec.compiler is not None:
                word = spec.compiler(row, intended)
                compiled.update({
                    'status': 'compiled',
                    'word': word,
                    'note': spec.note,
                })
                if word:
                    compiled_words.append(word)
                native_ops[op] = native_ops.get(op, 0) + 1
            else:
                fallback_words = list(row.get('commands') or [])
                fallback_word = fallback_words[min(command_index, len(fallback_words) - 1)] if fallback_words else None
                reason = spec.note if spec else f'No opcode registry entry is implemented yet for {op}.'
                compiled.update({
                    'status': 'fallback',
                    'word': fallback_word,
                    'fallback': {
                        'mode': row.get('fallback_mode') or 'sample_jump_title',
                        'reason': reason,
                    },
                })
                if fallback_word:
                    compiled_words.append(fallback_word)
                unsupported_ops[op] = unsupported_ops.get(op, 0) + 1
            compiled_rows.append(compiled)

        compiled_objects.append({
            **row,
            'compiled_commands': compiled_rows,
            'commands': compiled_words or list(row.get('commands') or []),
        })

    compiler_status = 'compiled_with_fallbacks' if unsupported_ops else 'compiled_native_registry_only'
    return {
        **movieobject_plan,
        'compiler_status': compiler_status,
        'opcode_registry': {
            name: {'mode': spec.mode, 'note': spec.note}
            for name, spec in registry.items()
        },
        'native_ops': native_ops,
        'unsupported_ops': unsupported_ops,
        'objects': compiled_objects,
    }


def _write_hdmv_lite_movieobject_xml(path: Path, hdmv_model: dict[str, Any]):
    plan = compile_hdmv_movieobject_commands(compile_hdmv_movieobject_plan(hdmv_model))
    objects = []
    for row in plan['objects']:
        note = row.get('notes') or 'HDMV-Lite command plan row'
        commands_xml = '\n'.join(
            f'            <navigationCommands commandId="{idx}">\n                <command>{cmd}</command>\n            </navigationCommands>'
            for idx, cmd in enumerate(row.get('commands') or [])
        )
        fallback_notes = []
        for compiled in row.get('compiled_commands') or []:
            if compiled.get('status') == 'fallback':
                fallback = compiled.get('fallback') or {}
                fallback_notes.append(
                    f"cmd[{compiled.get('command_index')}] {compiled.get('op')} -> fallback {fallback.get('mode')}: {fallback.get('reason')}"
                )
        comment = note if not fallback_notes else note + ' | ' + ' | '.join(fallback_notes)
        objects.append(f"""        <!-- {escape(comment)} -->
        <movieObject mobjId=\"{int(row.get('mobj_id') or 0)}\">
{commands_xml}
            <terminalInfo>
                <menuCallMask>false</menuCallMask>
                <resumeIntentionFlag>false</resumeIntentionFlag>
                <titleSearchMask>false</titleSearchMask>
            </terminalInfo>
        </movieObject>""")
    path.write_text(f"""<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>
<movieObjectFile>
    <version>0200</version>
    <movieObjects>
{chr(10).join(objects)}
    </movieObjects>
    <extensionData/>
    <paddingsN1>0</paddingsN1>
    <paddingsN2>0</paddingsN2>
</movieObjectFile>
""", encoding='utf-8')


def _write_hdmv_movieobject_plan_json(path: Path, hdmv_model: dict[str, Any]):
    plan = compile_hdmv_movieobject_commands(compile_hdmv_movieobject_plan(hdmv_model))
    path.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')


def detect_hdmv_validation_tools(root: Path) -> dict[str, dict[str, Any]]:
    """Describe available external validation oracles for HDMV output."""
    checks = {
        'index_dump': {'path_hint': 'PATH', 'argv': ['index_dump', '{disc_root}']},
        'mobj_dump': {'path_hint': 'PATH', 'argv': ['mobj_dump', '-d', '{movieobject_bdmv}']},
        'mpls_dump': {'path_hint': 'PATH', 'argv': ['mpls_dump', '-i', '-c', '-p', '{playlist_sample}']},
        'clpi_dump': {'path_hint': 'PATH', 'argv': ['clpi_dump', '-c', '-p', '-i', '{clipinfo_sample}']},
        'hdmv_test': {'path_hint': 'PATH', 'argv': ['hdmv_test', '-v', '{disc_root}']},
        'sound_dump': {'path_hint': 'PATH', 'argv': ['sound_dump', '{sound_bdmv}']},
    }
    out: dict[str, dict[str, Any]] = {}
    for name, meta in checks.items():
        found = shutil.which(name)
        out[name] = {
            'available': bool(found),
            'resolved_path': found,
            'path_hint': meta['path_hint'],
            'argv_template': meta['argv'],
        }

    out['index_jar'] = {
        'available': (root / 'DiscCreationTools' / 'index' / 'dist' / 'index.jar').exists(),
        'resolved_path': str(root / 'DiscCreationTools' / 'index' / 'dist' / 'index.jar'),
        'path_hint': 'bundled',
        'argv_template': ['java', '-jar', str(root / 'DiscCreationTools' / 'index' / 'dist' / 'index.jar'), '{index_xml}', '{index_bdmv}'],
    }
    out['movieobject_jar'] = {
        'available': (root / 'DiscCreationTools' / 'movieobject' / 'dist' / 'movieobject.jar').exists(),
        'resolved_path': str(root / 'DiscCreationTools' / 'movieobject' / 'dist' / 'movieobject.jar'),
        'path_hint': 'bundled',
        'argv_template': ['java', '-jar', str(root / 'DiscCreationTools' / 'movieobject' / 'dist' / 'movieobject.jar'), '{movieobject_xml}', '{movieobject_bdmv}'],
    }
    return out


def build_hdmv_validation_report(*, root: Path, disc_root: Path, package_dir: Path) -> dict[str, Any]:
    tools = detect_hdmv_validation_tools(root)
    playlist_sample = disc_root / 'BDMV' / 'PLAYLIST' / '00000.mpls'
    clipinfo_sample = disc_root / 'BDMV' / 'CLIPINF' / '00000.clpi'
    sound_bdmv = disc_root / 'BDMV' / 'AUXDATA' / 'sound.bdmv'
    context = {
        'disc_root': str(disc_root),
        'movieobject_bdmv': str(disc_root / 'BDMV' / 'MovieObject.bdmv'),
        'playlist_sample': str(playlist_sample),
        'clipinfo_sample': str(clipinfo_sample),
        'sound_bdmv': str(sound_bdmv),
        'index_xml': str(package_dir / 'index.xml'),
        'index_bdmv': str(disc_root / 'BDMV' / 'index.bdmv'),
        'movieobject_xml': str(package_dir / 'MovieObject.xml'),
    }
    commands = []
    for name, meta in tools.items():
        argv = [token.format(**context) for token in meta.get('argv_template') or []]
        commands.append({
            'tool': name,
            'available': bool(meta.get('available')),
            'argv': argv,
        })

    return {
        'schema_version': 'auto-bluray-hdmv-validation-report-v1',
        'disc_root': str(disc_root),
        'package_dir': str(package_dir),
        'tooling': tools,
        'commands': commands,
        'notes': [
            'Availability reflects PATH/bundled-tool detection on the build host.',
            'Successful detection does not guarantee the generated HDMV package is playback-correct; use dump tools and real player checks as follow-up oracles.',
        ],
    }


def build_hdmv_validation_runbook(report: dict[str, Any]) -> str:
    """Render a shell runbook for external HDMV validation oracles."""
    lines = [
        '#!/usr/bin/env bash',
        'set -euo pipefail',
        '',
        '# Generated HDMV validation runbook',
        '# Run commands manually or as a batch on a host with the required tools installed.',
        '',
    ]
    for command in report.get('commands') or []:
        tool = command.get('tool') or 'unknown'
        argv = ' '.join(str(token) for token in command.get('argv') or [])
        if command.get('available'):
            lines.append(f'# AVAILABLE: {tool}')
            lines.append(argv)
        else:
            lines.append(f'# MISSING: {tool}')
            lines.append(f'# {argv}')
        lines.append('')
    return '\n'.join(lines).rstrip() + '\n'


def run_hdmv_validation_checks(
    report: dict[str, Any],
    *,
    runner: Callable[..., Any] | None = None,
    include_unavailable: bool = False,
) -> dict[str, Any]:
    """Execute available validator commands and capture basic results."""
    executor = runner or subprocess.run
    results = []
    for command in report.get('commands') or []:
        tool = command.get('tool') or 'unknown'
        available = bool(command.get('available'))
        argv = [str(token) for token in command.get('argv') or []]
        if not available and not include_unavailable:
            continue
        if not available:
            results.append({
                'tool': tool,
                'argv': argv,
                'available': False,
                'ok': False,
                'skipped': True,
                'returncode': None,
                'stdout': '',
                'stderr': 'tool unavailable on this host',
            })
            continue
        try:
            completed = executor(argv, capture_output=True, text=True, check=False)
            results.append({
                'tool': tool,
                'argv': argv,
                'available': True,
                'ok': int(getattr(completed, 'returncode', 1) or 0) == 0,
                'skipped': False,
                'returncode': int(getattr(completed, 'returncode', 1) or 0),
                'stdout': getattr(completed, 'stdout', ''),
                'stderr': getattr(completed, 'stderr', ''),
            })
        except Exception as exc:  # pragma: no cover - defensive guard
            results.append({
                'tool': tool,
                'argv': argv,
                'available': True,
                'ok': False,
                'skipped': False,
                'returncode': None,
                'stdout': '',
                'stderr': str(exc),
            })
    executed_count = sum(1 for row in results if not row.get('skipped'))
    skipped_count = sum(1 for row in results if row.get('skipped'))
    passed_count = sum(1 for row in results if row.get('ok'))
    failed_count = sum(1 for row in results if (not row.get('ok')) and (not row.get('skipped')))
    return {
        'schema_version': 'auto-bluray-hdmv-validation-run-v1',
        'command_count': len(results),
        'executed_count': executed_count,
        'skipped_count': skipped_count,
        'passed_count': passed_count,
        'failed_count': failed_count,
        'ok': failed_count == 0,
        'results': results,
    }


def _write_hdmv_validation_report(path: Path, *, root: Path, disc_root: Path, package_dir: Path):
    report = build_hdmv_validation_report(root=root, disc_root=disc_root, package_dir=package_dir)
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


def _write_hdmv_validation_runbook(path: Path, report: dict[str, Any]):
    path.write_text(build_hdmv_validation_runbook(report), encoding='utf-8')
    with contextlib.suppress(OSError):
        path.chmod(path.stat().st_mode | 0o111)


def _write_hdmv_validation_run(path: Path, report: dict[str, Any]):
    run_result = run_hdmv_validation_checks(report, include_unavailable=True)
    path.write_text(json.dumps(run_result, indent=2) + '\n', encoding='utf-8')


def _try_compile_hdmv_xml(root: Path, xml_path: Path, binary_path: Path) -> bool:
    tool_name = 'index' if xml_path.name == 'index.xml' else 'movieobject'
    jar_name = 'index.jar' if tool_name == 'index' else 'movieobject.jar'
    jar_path = root / 'DiscCreationTools' / tool_name / 'dist' / jar_name
    if not jar_path.exists():
        return False
    try:
        run(['java', '-jar', jar_path, xml_path, binary_path])
        return binary_path.exists()
    except subprocess.CalledProcessError:
        return False


class HdmvMenuBackend(MenuBackend):
    name = 'hdmv'
    description = 'Experimental HDMV-Lite scaffold: exports static menu IR/metadata only; not a functional final menu compiler yet.'

    def install(self, *, root: Path, project: Path, menu_dir: Path, disc_root: Path, output_root: Path, model: dict[str, Any]) -> dict[str, Any]:
        report = write_compatibility_report(menu_dir, model, requested_backend='hdmv', selected_backend='hdmv')
        if not report.get('hdmv_safe'):
            reasons = [r['detail'] for r in report.get('bdj_required_features', []) + report.get('unsupported_features', [])]
            raise MenuBackendError(
                'HDMV menu backend was selected, but this PowerPoint menu is not HDMV-safe. '
                'Use --menu-backend bdj or --menu-backend auto, or remove BD-J-only features. '
                'Compatibility report: ' + str(menu_dir / 'menu-compatibility.md') + '\n- ' + '\n- '.join(reasons)
            )

        hdmv_model, errors = build_hdmv_lite_model(model, menu_dir)
        if errors:
            details = '\n- '.join(e['message'] for e in errors)
            raise MenuBackendError(
                'HDMV-Lite menu backend was selected, but this menu exceeds the first milestone scope. '
                'Supported scope: static menu pages, one background image per page, rectangular button hitboxes, '
                'and play-title/go-to-menu/return-main-menu actions.\n- ' + details
            )

        bdmv = disc_root / 'BDMV'
        shutil.rmtree(bdmv / 'JAR', ignore_errors=True)
        shutil.rmtree(bdmv / 'BDJO', ignore_errors=True)
        for dirname in ('AUXDATA', 'BACKUP', 'CLIPINF', 'PLAYLIST', 'STREAM'):
            (bdmv / dirname).mkdir(parents=True, exist_ok=True)
        (disc_root / 'CERTIFICATE' / 'BACKUP').mkdir(parents=True, exist_ok=True)

        package_dir = output_root / 'hdmv-lite'
        assets_dir = package_dir / 'assets'
        package_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)
        for page in hdmv_model.get('menus') or []:
            background = page.get('background') or {}
            background_file = background.get('file')
            if background_file:
                src = menu_dir / background_file
                dst = assets_dir / Path(background_file).name
                if src.exists():
                    shutil.copy2(src, dst)
                background['package_file'] = str(dst.relative_to(package_dir))

        generate_hdmv_button_state_assets(hdmv_model, package_dir)

        (package_dir / 'hdmv-lite-menu.json').write_text(json.dumps(hdmv_model, indent=2) + '\n', encoding='utf-8')
        ig_plan = build_hdmv_ig_plan(hdmv_model)
        for menu in hdmv_model.get('menus') or []:
            for button in menu.get('buttons') or []:
                for state_name in ('selected', 'activated'):
                    asset_file = ((button.get('state_assets') or {}).get(state_name))
                    object_id = ((button.get('object_refs') or {}).get(state_name))
                    if asset_file and object_id:
                        ig_plan['objects'].append({
                            'id': object_id,
                            'kind': 'button_state_bitmap',
                            'menu_id': menu.get('id'),
                            'button_id': button.get('id'),
                            'state': state_name,
                            'file': asset_file,
                            'width': int((button.get('hitbox_px') or {}).get('w') or 1),
                            'height': int((button.get('hitbox_px') or {}).get('h') or 1),
                        })
        (package_dir / 'hdmv-lite-ig-plan.json').write_text(json.dumps(ig_plan, indent=2) + '\n', encoding='utf-8')
        ig_tables = compile_hdmv_ig_tables(ig_plan)
        (package_dir / 'hdmv-lite-ig-tables.json').write_text(json.dumps(ig_tables, indent=2) + '\n', encoding='utf-8')
        ig_assembly = compile_hdmv_ig_assembly(ig_tables)
        (package_dir / 'hdmv-lite-ig-assembly.json').write_text(json.dumps(ig_assembly, indent=2) + '\n', encoding='utf-8')
        ig_binary = pack_hdmv_ig_binary_scaffold(ig_assembly)
        (package_dir / 'hdmv-lite-ig-binary-scaffold.json').write_text(json.dumps(ig_binary, indent=2) + '\n', encoding='utf-8')
        (package_dir / 'hdmv-lite-ig-scaffold.bin').write_bytes(materialize_hdmv_ig_binary_scaffold(ig_binary))
        ig_container = compile_hdmv_ig_packet_container(ig_binary)
        (package_dir / 'hdmv-lite-ig-packet-container.json').write_text(json.dumps(ig_container, indent=2) + '\n', encoding='utf-8')
        (package_dir / 'hdmv-lite-ig-packet-container.bin').write_bytes(materialize_hdmv_ig_packet_container(ig_container))
        (package_dir / 'README.md').write_text(
            '# HDMV-Lite menu package\n\n'
            'Generated by the first HDMV-Lite backend milestone.\n\n'
            '- static menu/page/button/action IR\n'
            '- lower-level IG planning IR for pages/BOGs/buttons/objects\n'
            '- normalized IG tables with stable numeric indexes for future binary encoding\n'
            '- serializer-shaped IG assembly export with reference validation\n'
            '- deterministic byte-oriented IG binary scaffold sections and concatenated `.bin` blob\n'
            '- deterministic packet/container scaffold JSON plus concatenated `.bin` blob\n'
            '- generated selected/activated button-state bitmap overlays\n'
            '- no BD-J/JAR/BDJO payloads\n'
            '- explicit MovieObject graph for first-play/top-menu/menu-page/title routing plus sample-backed compiled command fallback\n\n'
            'Interactive Graphics stream and final HDMV command bytecode compilation are the next milestone.\n',
            encoding='utf-8',
        )
        _write_hdmv_lite_index_xml(package_dir / 'index.xml', len(hdmv_model.get('titles') or []))
        _write_hdmv_movieobject_plan_json(package_dir / 'movieobject-plan.json', hdmv_model)
        _write_hdmv_lite_movieobject_xml(package_dir / 'MovieObject.xml', hdmv_model)
        compiled_index = _try_compile_hdmv_xml(root, package_dir / 'index.xml', bdmv / 'index.bdmv')
        compiled_mobj = _try_compile_hdmv_xml(root, package_dir / 'MovieObject.xml', bdmv / 'MovieObject.bdmv')
        validation_report = build_hdmv_validation_report(root=root, disc_root=disc_root, package_dir=package_dir)
        (package_dir / 'validation-report.json').write_text(json.dumps(validation_report, indent=2) + '\n', encoding='utf-8')
        _write_hdmv_validation_runbook(package_dir / 'validation-commands.sh', validation_report)
        _write_hdmv_validation_run(package_dir / 'validation-run.json', validation_report)

        for name in ('index.bdmv', 'MovieObject.bdmv'):
            src = bdmv / name
            if src.exists():
                shutil.copy2(src, bdmv / 'BACKUP' / name)

        return {
            'backend': self.name,
            'menu_dir': str(menu_dir),
            'hdmv_lite_package': str(package_dir),
            'hdmv_lite_model': str(package_dir / 'hdmv-lite-menu.json'),
            'hdmv_lite_ig_plan': str(package_dir / 'hdmv-lite-ig-plan.json'),
            'hdmv_lite_ig_tables': str(package_dir / 'hdmv-lite-ig-tables.json'),
            'hdmv_lite_ig_assembly': str(package_dir / 'hdmv-lite-ig-assembly.json'),
            'hdmv_lite_ig_binary_scaffold': str(package_dir / 'hdmv-lite-ig-binary-scaffold.json'),
            'hdmv_lite_ig_scaffold_bin': str(package_dir / 'hdmv-lite-ig-scaffold.bin'),
            'hdmv_lite_ig_packet_container': str(package_dir / 'hdmv-lite-ig-packet-container.json'),
            'hdmv_lite_ig_packet_container_bin': str(package_dir / 'hdmv-lite-ig-packet-container.bin'),
            'index_xml': str(package_dir / 'index.xml'),
            'movieobject_xml': str(package_dir / 'MovieObject.xml'),
            'movieobject_plan': str(package_dir / 'movieobject-plan.json'),
            'validation_report': str(package_dir / 'validation-report.json'),
            'validation_runbook': str(package_dir / 'validation-commands.sh'),
            'validation_run': str(package_dir / 'validation-run.json'),
            'index_bdmv': str(bdmv / 'index.bdmv') if compiled_index else None,
            'movieobject_bdmv': str(bdmv / 'MovieObject.bdmv') if compiled_mobj else None,
            'java_payload': False,
            'compiler_status': hdmv_model['compiler_status'],
        }


def backend_for(name: str) -> MenuBackend:
    if name == 'bdj':
        return BdjMenuBackend()
    if name == 'hdmv':
        return HdmvMenuBackend()
    raise MenuBackendError(f'Unknown resolved menu backend: {name}')


def add_pptx_menu_assets_to_jar(menu_dir: Path, jar_path: Path):
    assets_dir = menu_dir / 'assets'
    if not assets_dir.exists():
        raise MenuBackendError(f'Missing generated PptxMenu assets: {assets_dir}')
    with zipfile.ZipFile(jar_path, 'a', zipfile.ZIP_DEFLATED) as zf:
        for asset in sorted(assets_dir.rglob('*')):
            if asset.is_file():
                zf.write(asset, asset.relative_to(menu_dir).as_posix())


def sign_pptx_menu_jar(root: Path, disc_root: Path, output_root: Path):
    security_jar = root / 'bin' / 'security.jar'
    bc_jar = root / 'bin' / 'bcprov-jdk15-137.jar'
    jar_path = disc_root / 'BDMV' / 'JAR' / '00000.jar'
    cert_work = output_root / 'cert-work'
    cert_work.mkdir(parents=True, exist_ok=True)
    if not security_jar.exists() or not bc_jar.exists():
        raise MenuBackendError(f'Missing BD-J signing tools: {security_jar} or {bc_jar}')

    tools_jar_candidates = []
    java_home = os.environ.get('JAVA_HOME')
    if java_home:
        tools_jar_candidates.append(Path(java_home) / 'lib' / 'tools.jar')
    tools_jar_candidates.extend([
        Path('/usr/lib/jvm/default/lib/tools.jar'),
        Path('/usr/lib/jvm/java-8-openjdk/lib/tools.jar'),
    ])
    tools_jar = next((p for p in tools_jar_candidates if p.exists()), None)
    cp_entries = [security_jar]
    if tools_jar:
        cp_entries.append(tools_jar)
    cp_entries.append(bc_jar)
    cp = os.pathsep.join(str(p) for p in cp_entries)
    run(['java', '-cp', cp, 'net.java.bd.tools.security.BDCertGenerator', '-debug', '-root', '56789abc'], cwd=cert_work)
    run(['java', '-cp', cp, 'net.java.bd.tools.security.BDCertGenerator', '-debug', '-app', '56789abc'], cwd=cert_work)
    run(['java', '-cp', cp, 'net.java.bd.tools.security.BDSigner', '-debug', jar_path], cwd=cert_work)
    cert = cert_work / 'app.discroot.crt'
    if cert.exists():
        for dst in (disc_root / 'CERTIFICATE' / 'app.discroot.crt', disc_root / 'CERTIFICATE' / 'BACKUP' / 'app.discroot.crt'):
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cert, dst)
