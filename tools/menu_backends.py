#!/usr/bin/env python3
"""Menu backend selection and HDMV/BD-J scaffolding.

The PowerPoint converter produces a backend-neutral menu model.  This module
keeps backend-specific build/install logic out of the converter so the project
can grow from today's GRIN/BD-J implementation toward HDMV-Lite.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw

MENU_BACKENDS = ('bdj', 'hdmv', 'auto')
DEFAULT_MENU_BACKEND = 'bdj'
HDMV_COMPILER_STATUS = 'ir_only_first_milestone'
HDMV_FUNCTIONAL_COMPILER_STATUSES = {'functional'}


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
    page_indexes = {row.get('page_index') for row in page_table}
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
    for page in page_table:
        if page.get('menu_id') == entry_menu:
            entry_page_index = page.get('page_index')
            break
    if entry_menu is not None and entry_page_index is None:
        errors.append({'type': 'invalid_entry_menu', 'entry_menu': entry_menu})

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

    menu_to_page_index = {
        page.get('page_id'): page.get('page_index') for page in pages
    }
    menu_name_to_page_index = {
        # populated conservatively from assembly pages if menu_id is later added here
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
        target_menu = action.get('target_menu')
        target_page_index = None
        if target_menu is not None:
            target_page_index = menu_name_to_page_index.get(target_menu)
            if target_page_index is None and isinstance(target_menu, str) and target_menu.startswith('slide'):
                try:
                    target_page_index = int(target_menu.replace('slide', '')) - 1
                except ValueError:
                    target_page_index = None
        action_records.extend(_pack_u16(_pack_optional_u16(target_page_index)))

    for page in sorted(pages, key=lambda row: int(row.get('page_index') or 0)):
        page_index = int(page.get('page_index') or 0)
        buttons = sorted(page.get('buttons') or [], key=lambda row: int(row.get('button_index') or 0))
        bogs = sorted(page.get('bogs') or [], key=lambda row: int(row.get('bog_index') or 0))
        if len(buttons) > 0xFFFF or len(bogs) > 0xFFFF:
            raise MenuBackendError(f'Cannot pack HDMV IG binary scaffold: page {page_index} exceeds scaffold count limits.')
        page_records.extend(_pack_u16(page_index))
        page_records.extend(_pack_u16(int(page.get('page_id') or 0)))
        page_records.extend(_pack_u16(int(page.get('background_object_index') or 0)))
        page_records.extend(_pack_u16(_pack_optional_u16(page.get('default_selected_button_index'))))
        page_records.extend(_pack_u16(len(buttons)))
        page_records.extend(_pack_u16(len(bogs)))

        for button in buttons:
            neighbors = button.get('neighbor_button_indexes') or {}
            object_indexes = button.get('object_indexes') or {}
            button_records.extend(_pack_u16(page_index))
            button_records.extend(_pack_u16(int(button.get('button_index') or 0)))
            button_records.extend(_pack_u16(int(button.get('select_value') or 0)))
            button_records.extend(_pack_u16(_pack_optional_u16(neighbors.get('left'))))
            button_records.extend(_pack_u16(_pack_optional_u16(neighbors.get('right'))))
            button_records.extend(_pack_u16(_pack_optional_u16(neighbors.get('up'))))
            button_records.extend(_pack_u16(_pack_optional_u16(neighbors.get('down'))))
            button_records.extend(_pack_u16(int(object_indexes.get('normal') or 0)))
            button_records.extend(_pack_u16(_pack_optional_u16(object_indexes.get('selected'))))
            button_records.extend(_pack_u16(_pack_optional_u16(object_indexes.get('activated'))))
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
        })
        offset += len(payload)

    return {
        'schema_version': 'auto-bluray-hdmv-ig-binary-scaffold-v1',
        'entry_page_index': ig_assembly.get('entry_page_index'),
        'total_size': offset,
        'sections': sections,
        'notes': [
            'Deterministic byte-oriented scaffold only; not a final HDMV IG bitstream.',
            'Next milestone should replace these placeholder record layouts with real HDMV IG binary field semantics.',
        ],
    }


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
        mobj_id = i + 1
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
                <playbackType>HDMVPlayback_INTERACTIVE</playbackType>
            </firstPlaybackObject>
        </firstPlayback>
        <topMenu>
            <topMenuObject xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:type=\"HDMVIndexObject\">
                <HDMVName>0x0</HDMVName>
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


def _write_hdmv_lite_movieobject_xml(path: Path, hdmv_model: dict[str, Any]):
    objects = []
    object_count = 1 + len(hdmv_model.get('titles') or [])
    for mobj_id in range(object_count):
        note = 'Top menu IG program placeholder' if mobj_id == 0 else f'Title {mobj_id} playback command placeholder'
        objects.append(f"""        <!-- {escape(note)}. The HDMV-Lite first milestone emits IR and static navigation metadata; IG/action bytecode compilation follows. -->
        <movieObject mobjId=\"{mobj_id}\">
            <navigationCommands commandId=\"0\">
                <command>00000000 00000000 00000000</command>
            </navigationCommands>
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
        (package_dir / 'README.md').write_text(
            '# HDMV-Lite menu package\n\n'
            'Generated by the first HDMV-Lite backend milestone.\n\n'
            '- static menu/page/button/action IR\n'
            '- lower-level IG planning IR for pages/BOGs/buttons/objects\n'
            '- normalized IG tables with stable numeric indexes for future binary encoding\n'
            '- serializer-shaped IG assembly export with reference validation\n'
            '- deterministic byte-oriented IG binary scaffold sections\n'
            '- generated selected/activated button-state bitmap overlays\n'
            '- no BD-J/JAR/BDJO payloads\n'
            '- Java-free index/MovieObject skeletons when DiscCreationTools are available\n\n'
            'Interactive Graphics stream and final HDMV command bytecode compilation are the next milestone.\n',
            encoding='utf-8',
        )
        _write_hdmv_lite_index_xml(package_dir / 'index.xml', len(hdmv_model.get('titles') or []))
        _write_hdmv_lite_movieobject_xml(package_dir / 'MovieObject.xml', hdmv_model)
        compiled_index = _try_compile_hdmv_xml(root, package_dir / 'index.xml', bdmv / 'index.bdmv')
        compiled_mobj = _try_compile_hdmv_xml(root, package_dir / 'MovieObject.xml', bdmv / 'MovieObject.bdmv')

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
            'index_xml': str(package_dir / 'index.xml'),
            'movieobject_xml': str(package_dir / 'MovieObject.xml'),
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
