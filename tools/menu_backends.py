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

MENU_BACKENDS = ('hdmv', 'bdj', 'auto')
DEFAULT_MENU_BACKEND = 'hdmv'


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
    other_actions = [a for a in actions if a.get('kind') not in ('video', 'slide')]
    if video_actions:
        safe.append(_feature('hdmv_safe', 'play_title_actions', f'{len(video_actions)} play-title action(s) targeting Blu-ray playlist ids.', hdmv_phase='v0.5'))
    if slide_actions:
        safe.append(_feature('hdmv_safe', 'menu_page_navigation', f'{len(slide_actions)} go-to-menu/page action(s).', hdmv_phase='v0.5'))
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
        return 'hdmv' if report.get('hdmv_safe') else 'bdj'
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


class HdmvMenuBackend(MenuBackend):
    name = 'hdmv'
    description = 'HDMV-Lite scaffold; validates compatibility but does not compile HDMV IG/MovieObject artifacts yet.'

    def install(self, *, root: Path, project: Path, menu_dir: Path, disc_root: Path, output_root: Path, model: dict[str, Any]) -> dict[str, Any]:
        report = write_compatibility_report(menu_dir, model, requested_backend='hdmv', selected_backend='hdmv')
        if not report.get('hdmv_safe'):
            reasons = [r['detail'] for r in report.get('bdj_required_features', []) + report.get('unsupported_features', [])]
            raise MenuBackendError(
                'HDMV menu backend was selected, but this PowerPoint menu is not HDMV-safe. '\
                'Use --menu-backend bdj or --menu-backend auto, or remove BD-J-only features. '\
                'Compatibility report: ' + str(menu_dir / 'menu-compatibility.md') + '\n- ' + '\n- '.join(reasons)
            )
        raise MenuBackendError(
            'HDMV-Lite menu backend is scaffolded but actual HDMV compilation is not implemented yet. '\
            'The menu model validates as HDMV-safe, and a compatibility report was written to '\
            f'{menu_dir / "menu-compatibility.md"}. Use --menu-backend bdj for a working disc until the HDMV-Lite compiler milestone lands.'
        )


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
