#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def run(cmd, **kwargs):
    print('+', ' '.join(str(x) for x in cmd), flush=True)
    return subprocess.run([str(x) for x in cmd], check=True, **kwargs)


def read_json(path: Path):
    return json.loads(path.read_text())


def which(root: Path, name: str):
    local = root / 'tools' / 'bin' / name
    if local.exists():
        return local
    if name == 'tsMuxer':
        for alt in ('tsMuxeR', 'tsmuxer'):
            local_alt = root / 'tools' / 'bin' / alt
            if local_alt.exists():
                return local_alt
    found = shutil.which(name)
    return Path(found) if found else None


def ffprobe(path: Path):
    result = subprocess.run([
        'ffprobe', '-hide_banner', '-v', 'error',
        '-show_entries', 'format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,sample_rate',
        '-of', 'json', str(path),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    return json.loads(result.stdout)


def validate_encoded(path: Path, source_duration: float|None, *, allow_oversized=False):
    if not path.exists() or path.stat().st_size <= 0:
        raise SystemExit(f'Missing encoded file: {path}')
    data = ffprobe(path)
    fmt = data.get('format') or {}
    streams = data.get('streams') or []
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    duration = float(fmt.get('duration') or 0)
    bit_rate = int(fmt.get('bit_rate') or 0)
    if source_duration and duration < source_duration - 2:
        raise SystemExit(f'Encoded file is not full length: {path} ({duration:.1f}s < {source_duration:.1f}s)')
    if not video or video.get('codec_name') != 'h264':
        raise SystemExit(f'Encoded file is not H.264 video: {path}')
    if not audio or audio.get('codec_name') != 'ac3' or str(audio.get('sample_rate') or '') != '48000':
        raise SystemExit(f'Encoded file is not 48 kHz AC-3 audio: {path}')
    if not allow_oversized and bit_rate and bit_rate > 7_200_000:
        raise SystemExit(f'Encoded file is too large for BD-25 target: {path} ({bit_rate/1_000_000:.1f} Mb/s)')
    return {'duration': duration, 'bit_rate': bit_rate, 'size': int(fmt.get('size') or path.stat().st_size)}


def patch_clip_id(src: Path, dst: Path, old='00000', new='00001'):
    data = src.read_bytes()
    data = data.replace(old.encode('ascii'), new.encode('ascii'))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)


def tsmuxer_tracks(ts_muxer: Path, encoded: Path):
    result = subprocess.run([str(ts_muxer), str(encoded)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True)
    tracks = []
    current = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith('Track ID:'):
            if current:
                tracks.append(current)
            current = {'track': line.split(':', 1)[1].strip()}
        elif line.startswith('Stream ID:') and current:
            current['stream_id'] = line.split(':', 1)[1].strip()
        elif line.startswith('Stream delay:') and current:
            current['delay'] = line.split(':', 1)[1].strip()
    if current:
        tracks.append(current)
    video = next((t for t in tracks if t.get('stream_id') == 'V_MPEG4/ISO/AVC'), None)
    audio = next((t for t in tracks if t.get('stream_id') == 'A_AC3'), None)
    if not video or not audio:
        raise SystemExit(f'Could not detect H.264/AC-3 tracks in {encoded}:\n{result.stdout}')
    return video, audio


def subtitle_language(path: Path) -> str:
    stem = path.stem.lower()
    if 'spanish' in stem or ' esp' in stem or '.es' in stem:
        return 'spa'
    if 'french' in stem or ' fra' in stem or ' fre' in stem or '.fr' in stem:
        return 'fra'
    if 'german' in stem or ' ger' in stem or ' deu' in stem or '.de' in stem:
        return 'deu'
    if 'english' in stem or ' eng' in stem or '.en' in stem:
        return 'eng'
    return 'eng'


def matching_subtitles(project: Path, video_file: str, manifest: dict) -> list[dict]:
    """Return sidecar subtitles for a video, preferring manifest metadata.

    Blu-ray muxing is done per title, so sidecars named like `Video 4.srt` or
    `Video 4 Spanish.srt` should be included with `Video 4.mp4`.
    """
    video_stem = Path(video_file).stem.lower()
    manifest_rows = {v.get('file'): v for v in manifest.get('videos', [])}
    rows = []
    for sub in manifest_rows.get(video_file, {}).get('sidecar_subtitles', []) or []:
        p = project / sub.get('file', '')
        if p.exists():
            rows.append({'path': p, 'language': sub.get('language') or subtitle_language(p)})
    if not rows:
        for p in sorted(project.iterdir(), key=lambda x: x.name.lower()):
            if p.suffix.lower() not in ('.srt', '.sup'):
                continue
            if p.stem.lower().startswith(video_stem):
                rows.append({'path': p, 'language': subtitle_language(p)})
    # Put the exact same-name subtitle first so it becomes the first selectable
    # subtitle track; keep alternates like "Spanish" after it.
    rows.sort(key=lambda r: (Path(r['path']).stem.lower() != video_stem, Path(r['path']).name.lower()))
    return rows


def write_meta(path: Path, encoded: Path, ts_muxer: Path, subtitles: list[dict]|None = None):
    video, audio = tsmuxer_tracks(ts_muxer, encoded)
    audio_delay = audio.get('delay')
    audio_params = f'track={audio["track"]}, lang=eng'
    if audio_delay:
        audio_params += f', timeshift={audio_delay}'
    lines = [
        'MUXOPT --blu-ray --vbr --auto-chapters=5 --new-audio-pes',
        f'V_MPEG4/ISO/AVC, "{encoded}", track={video["track"]}, fps=23.976, insertSEI, contSPS',
        f'A_AC3, "{encoded}", {audio_params}',
    ]
    for sub in subtitles or []:
        sub_path = Path(sub['path'])
        codec = 'S_HDMV/PGS' if sub_path.suffix.lower() == '.sup' else 'S_TEXT/UTF8'
        lang = (sub.get('language') or subtitle_language(sub_path))[:3]
        params = f'lang={lang}, video-width=1920, video-height=1080, fps=23.976'
        if codec == 'S_TEXT/UTF8':
            params += ', font-name="DejaVu Sans", font-size=45, font-color=0xffffffff, font-border=2, bottom-offset=24'
        lines.append(f'{codec}, "{sub_path}", {params}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def copytree_contents(src: Path, dst: Path):
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def help_text(cmd: list[Path|str]) -> str:
    try:
        result = subprocess.run([str(x) for x in cmd] + ['-help'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        return result.stdout or ''
    except OSError:
        return ''


def mkisofs_udf_command(root: Path) -> list[Path|str]|None:
    candidates: list[list[Path|str]] = []
    for name in ('mkisofs', 'genisoimage', 'xorrisofs'):
        tool = which(root, name)
        if tool:
            candidates.append([tool])
    xorriso = which(root, 'xorriso')
    if xorriso:
        candidates.append([xorriso, '-as', 'mkisofs'])

    for cmd in candidates:
        text = help_text(cmd).lower()
        if '-udf' in text or 'udf' in text:
            return cmd
    return None


def sanitize_volume_id(value: str) -> str:
    """Return a safe ISO/UDF volume ID for Blu-ray players and mkisofs."""
    value = (value or '').strip() or 'BLURAY_PROJECT'
    value = ''.join(ch if ch.isalnum() else '_' for ch in value.upper())
    value = '_'.join(part for part in value.split('_') if part)
    return (value or 'BLURAY_PROJECT')[:32]


def make_iso(mkisofs_cmd: list[Path|str], disc_root: Path, iso_path: Path, volume_id: str):
    iso_path.parent.mkdir(parents=True, exist_ok=True)
    if iso_path.exists():
        iso_path.unlink()

    cmd = [*mkisofs_cmd, '-iso-level', '3', '-udf', '-volid', sanitize_volume_id(volume_id), '-o', iso_path, disc_root]
    try:
        run(cmd)
    except subprocess.CalledProcessError:
        if iso_path.exists():
            iso_path.unlink()
        raise SystemExit(
            'Failed to create a UDF Blu-ray image. Refusing to fall back to plain ISO9660/Rock Ridge, '
            'because that can burn successfully but fail as a Blu-ray disc. Install a UDF-capable '
            'mkisofs/genisoimage/cdrtools package and rerun.'
        )


def build_pptx_menu(root: Path, project: Path) -> Path:
    """Regenerate and build the PowerPoint-derived GRIN/BD-J menu."""
    menu_dir = root / 'xlets' / 'grin_samples' / 'Scripts' / 'PptxMenu'
    run([root / 'scripts' / 'convert-pptx-menu.sh', project])
    run(['ant', 'default'], cwd=menu_dir)
    jar_path = menu_dir / 'build' / '00000.jar'
    bdjo_path = menu_dir / 'build' / '00000.bdjo'
    if not jar_path.exists() or not bdjo_path.exists():
        raise SystemExit(f'PptxMenu build did not create expected {jar_path} and {bdjo_path}')
    return menu_dir


def sign_pptx_menu_jar(root: Path, disc_root: Path, output_root: Path):
    """Sign the generated menu jar so BD-J/libbluray accepts media control."""
    security_jar = root / 'bin' / 'security.jar'
    bc_jar = root / 'bin' / 'bcprov-jdk15-137.jar'
    jar_path = disc_root / 'BDMV' / 'JAR' / '00000.jar'
    cert_work = output_root / 'cert-work'
    cert_work.mkdir(parents=True, exist_ok=True)
    if not security_jar.exists() or not bc_jar.exists():
        raise SystemExit(f'Missing BD-J signing tools: {security_jar} or {bc_jar}')

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


def add_pptx_menu_assets_to_jar(menu_dir: Path, jar_path: Path):
    """Package generated slide PNGs beside pptx-menu.grin in the menu jar."""
    assets_dir = menu_dir / 'assets'
    if not assets_dir.exists():
        raise SystemExit(f'Missing generated PptxMenu assets: {assets_dir}')
    with zipfile.ZipFile(jar_path, 'a', zipfile.ZIP_DEFLATED) as zf:
        for asset in sorted(assets_dir.rglob('*')):
            if asset.is_file():
                zf.write(asset, asset.relative_to(menu_dir).as_posix())


def install_pptx_menu_overlay(root: Path, project: Path, disc_root: Path, output_root: Path):
    menu_dir = build_pptx_menu(root, project)
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

    shutil.copy2(menu_dir / 'build' / '00000.jar', jar_dir / '00000.jar')
    add_pptx_menu_assets_to_jar(menu_dir, jar_dir / '00000.jar')
    shutil.copy2(menu_dir / 'build' / '00000.bdjo', bdjo_dir / '00000.bdjo')

    # The generated BDJO references default font file 00000.  Keep the sample
    # font if present; otherwise menu rendering still uses slide PNGs, but some
    # players expect this file to exist.
    sample_font = root / 'xlets' / 'hdcookbook_discimage' / 'dist' / 'DiscImage' / 'BDMV' / 'AUXDATA' / '00000.otf'
    if sample_font.exists() and not (aux_dir / '00000.otf').exists():
        shutil.copy2(sample_font, aux_dir / '00000.otf')

    sign_pptx_menu_jar(root, disc_root, output_root)
    return menu_dir


def refresh_playlist_map(root: Path, project: Path, menu_dir: Path) -> dict:
    """Regenerate the mux plan from the just-built PPTX menu actions."""
    run([root / 'tools' / 'bluray_mux_plan.py', project, '--menu-dir', menu_dir])
    playlist_map_path = project / 'build' / 'bluray-authoring' / 'playlist-map.json'
    if not playlist_map_path.exists():
        raise SystemExit(f'Missing {playlist_map_path}; mux plan generation failed')
    plan = read_json(playlist_map_path)
    rows = plan.get('video_playlist_map') or []
    if not rows:
        raise SystemExit('No video_playlist_map entries found')
    return plan


def validate_final_disc(disc_root: Path):
    """Fail fast if legacy sample menu/game artifacts leak into the final disc."""
    bdmv = disc_root / 'BDMV'
    jar_dir = bdmv / 'JAR'
    bdjo_dir = bdmv / 'BDJO'
    playlist_dir = bdmv / 'PLAYLIST'
    jar_path = jar_dir / '00000.jar'

    expected_jars = {'00000.jar'}
    actual_jars = {p.name for p in jar_dir.glob('*.jar')}
    if actual_jars != expected_jars:
        raise SystemExit(f'Unexpected BD-J jars in final disc: {sorted(actual_jars)}')

    expected_bdjos = {'00000.bdjo'}
    actual_bdjos = {p.name for p in bdjo_dir.glob('*.bdjo')}
    if actual_bdjos != expected_bdjos:
        raise SystemExit(f'Unexpected BDJO files in final disc: {sorted(actual_bdjos)}')

    if (playlist_dir / '00000.mpls').exists():
        raise SystemExit('Legacy first-play playlist BDMV/PLAYLIST/00000.mpls must not be present')

    forbidden = ('gunbunny', 'bookmenu', 'Game_', 'Bonus_', 'Scenes_', 'Graphics/Menu')
    path_hits = [str(p.relative_to(disc_root)) for p in disc_root.rglob('*') if any(s in str(p) for s in forbidden)]
    if path_hits:
        raise SystemExit('Legacy sample artifact paths found in final disc: ' + ', '.join(path_hits[:20]))

    with zipfile.ZipFile(jar_path) as zf:
        names = zf.namelist()
        grin_text = zf.read('pptx-menu.grin').decode('utf-8', errors='ignore') if 'pptx-menu.grin' in names else ''
    jar_hits = [n for n in names if any(s in n for s in forbidden)]
    if jar_hits:
        raise SystemExit('Legacy sample artifacts found in final menu jar: ' + ', '.join(jar_hits[:20]))

    # The menu can have any number of PPTX slides.  Older validation assumed the
    # sample 3-slide deck and falsely rejected valid single-slide menus.
    slide_assets = {n for n in names if n.startswith('assets/slide') and n.endswith('.png')}
    bg_assets = {n for n in slide_assets if n.rsplit('/', 1)[-1].endswith('_bg.png')}
    if not bg_assets:
        raise SystemExit('Generated PPTX slide background assets are missing from final menu jar')

    referenced_assets = set()
    for line in grin_text.splitlines():
        if '"assets/slide' not in line:
            continue
        parts = line.split('"')
        referenced_assets.update(p for p in parts if p.startswith('assets/slide') and p.endswith('.png'))
    missing_assets = sorted(referenced_assets - slide_assets)
    if missing_assets:
        raise SystemExit('Generated PPTX assets are missing from final menu jar: ' + ', '.join(missing_assets[:20]))


def main():
    ap = argparse.ArgumentParser(description='Assemble final Blu-ray BDMV tree and ISO from encoded videos + HD Cook Book menu overlay.')
    ap.add_argument('project_dir')
    ap.add_argument('--output-root', default=None)
    ap.add_argument('--volume-id', default=None, help='disc title / ISO volume label; sanitized to a 32-character volume ID')
    ap.add_argument('--allow-oversized', action='store_true', help='allow outputs above BD-25 bitrate guardrail')
    ap.add_argument('--no-iso', action='store_true', help='build final BDMV tree only')
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    root = Path(__file__).resolve().parents[1]
    volume_id = sanitize_volume_id(args.volume_id or project.name)
    output_root = Path(args.output_root).resolve() if args.output_root else project / 'build' / 'final-bluray'
    work = output_root / 'work'
    mux_work = work / 'muxed-titles'
    disc_root = output_root / 'disc-root'
    iso_path = output_root / 'bluray-project.iso'

    ts_muxer = which(root, 'tsMuxer')
    if not ts_muxer:
        raise SystemExit('Missing tsMuxer; run scripts/get-tsmuxer.sh first')
    mkisofs_cmd = mkisofs_udf_command(root) if not args.no_iso else None
    if not args.no_iso and not mkisofs_cmd:
        raise SystemExit(
            'Missing a UDF-capable ISO creator. Blu-ray images must be UDF; plain ISO9660/Rock Ridge images '
            'can burn but fail playback. Install cdrtools/mkisofs or genisoimage, then rerun, or use --no-iso '
            'to build the BDMV tree only.'
        )

    overlay_zip = root / 'xlets' / 'hdcookbook_discimage' / 'HDCookbookDiscImage.zip'
    if not overlay_zip.exists():
        raise SystemExit(f'Missing {overlay_zip}; run build-sample-disc.sh first')

    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(disc_root, ignore_errors=True)
    mux_work.mkdir(parents=True, exist_ok=True)
    disc_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(overlay_zip) as zf:
        zf.extractall(disc_root)

    menu_dir = install_pptx_menu_overlay(root, project, disc_root, output_root)
    plan = refresh_playlist_map(root, project, menu_dir)
    rows = plan.get('video_playlist_map') or []
    legacy_first_play = disc_root / 'BDMV' / 'PLAYLIST' / '00000.mpls'
    if legacy_first_play.exists():
        legacy_first_play.unlink()

    manifest_path = project / 'build' / 'bluray-media' / 'media-manifest.json'
    manifest = read_json(manifest_path) if manifest_path.exists() else {'videos': []}
    durations = {v['file']: float(v.get('duration_seconds') or 0) for v in manifest.get('videos', [])}

    summary = []
    for row in rows:
        playlist_id = str(row['playlist_id']).zfill(5)
        encoded = Path(row.get('encoded_abs') or (project / row['encoded_m2ts'])).resolve()
        info = validate_encoded(encoded, durations.get(row.get('video_file')), allow_oversized=args.allow_oversized)

        title_dir = mux_work / playlist_id
        title_dir.mkdir(parents=True, exist_ok=True)
        meta = title_dir / f'{playlist_id}.meta'
        subtitles = matching_subtitles(project, row.get('video_file', ''), manifest)
        write_meta(meta, encoded, ts_muxer, subtitles)
        run([ts_muxer, meta, title_dir / 'bd'])

        bdmv = title_dir / 'bd' / 'BDMV'
        stream_src = bdmv / 'STREAM' / '00000.m2ts'
        clpi_src = bdmv / 'CLIPINF' / '00000.clpi'
        mpls_src = bdmv / 'PLAYLIST' / '00000.mpls'
        if not stream_src.exists() or not clpi_src.exists() or not mpls_src.exists():
            raise SystemExit(f'tsMuxer did not create expected BDMV files for {encoded}')

        stream_dst = disc_root / 'BDMV' / 'STREAM' / f'{playlist_id}.m2ts'
        clpi_dst = disc_root / 'BDMV' / 'CLIPINF' / f'{playlist_id}.clpi'
        mpls_dst = disc_root / 'BDMV' / 'PLAYLIST' / f'{playlist_id}.mpls'
        stream_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stream_src, stream_dst)
        patch_clip_id(clpi_src, clpi_dst, '00000', playlist_id)
        patch_clip_id(mpls_src, mpls_dst, '00000', playlist_id)
        summary.append({
            **row,
            **info,
            'stream': str(stream_dst),
            'playlist': str(mpls_dst),
            'clipinf': str(clpi_dst),
            'subtitles': [{'file': s['path'].name, 'language': s.get('language') or subtitle_language(s['path'])} for s in subtitles],
        })

    backup = disc_root / 'BDMV' / 'BACKUP'
    shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True, exist_ok=True)
    for name in ('index.bdmv', 'MovieObject.bdmv'):
        src = disc_root / 'BDMV' / name
        if src.exists():
            shutil.copy2(src, backup / name)
    for dirname in ('BDJO', 'CLIPINF', 'PLAYLIST'):
        src = disc_root / 'BDMV' / dirname
        if src.exists():
            copytree_contents(src, backup / dirname)

    validate_final_disc(disc_root)

    report = {
        'project_dir': str(project),
        'disc_root': str(disc_root),
        'iso': str(iso_path) if not args.no_iso else None,
        'volume_id': volume_id,
        'titles': summary,
        'total_stream_bytes': sum(x['size'] for x in summary),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / 'final-report.json').write_text(json.dumps(report, indent=2) + '\n')

    if not args.no_iso:
        make_iso(mkisofs_cmd, disc_root, iso_path, volume_id)
        report['iso_bytes'] = iso_path.stat().st_size
        (output_root / 'final-report.json').write_text(json.dumps(report, indent=2) + '\n')

    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
