#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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


def write_meta(path: Path, encoded: Path, ts_muxer: Path):
    video, audio = tsmuxer_tracks(ts_muxer, encoded)
    audio_delay = audio.get('delay')
    audio_params = f'track={audio["track"]}, lang=eng'
    if audio_delay:
        audio_params += f', timeshift={audio_delay}'
    path.write_text(f'''MUXOPT --blu-ray --vbr --auto-chapters=5 --new-audio-pes
V_MPEG4/ISO/AVC, "{encoded}", track={video['track']}, fps=23.976, insertSEI, contSPS
A_AC3, "{encoded}", {audio_params}
''')


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


def make_iso(mkisofs_cmd: list[Path|str], disc_root: Path, iso_path: Path, volume_id: str):
    iso_path.parent.mkdir(parents=True, exist_ok=True)
    if iso_path.exists():
        iso_path.unlink()

    cmd = [*mkisofs_cmd, '-iso-level', '3', '-udf', '-volid', volume_id[:32], '-o', iso_path, disc_root]
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


def main():
    ap = argparse.ArgumentParser(description='Assemble final Blu-ray BDMV tree and ISO from encoded videos + HD Cook Book menu overlay.')
    ap.add_argument('project_dir')
    ap.add_argument('--output-root', default=None)
    ap.add_argument('--volume-id', default='BLURAY_PROJECT')
    ap.add_argument('--allow-oversized', action='store_true', help='allow outputs above BD-25 bitrate guardrail')
    ap.add_argument('--no-iso', action='store_true', help='build final BDMV tree only')
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    root = Path(__file__).resolve().parents[1]
    output_root = Path(args.output_root).resolve() if args.output_root else project / 'build' / 'final-bluray'
    work = output_root / 'work'
    mux_work = work / 'muxed-titles'
    disc_root = output_root / 'disc-root'
    iso_path = output_root / 'bluray-project.iso'

    playlist_map_path = project / 'build' / 'bluray-authoring' / 'playlist-map.json'
    if not playlist_map_path.exists():
        raise SystemExit(f'Missing {playlist_map_path}; run create-bluray-authoring-plan.sh first')
    plan = read_json(playlist_map_path)
    rows = plan.get('video_playlist_map') or []
    if not rows:
        raise SystemExit('No video_playlist_map entries found')

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
        write_meta(meta, encoded, ts_muxer)
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
        summary.append({**row, **info, 'stream': str(stream_dst), 'playlist': str(mpls_dst), 'clipinf': str(clpi_dst)})

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

    report = {
        'project_dir': str(project),
        'disc_root': str(disc_root),
        'iso': str(iso_path) if not args.no_iso else None,
        'titles': summary,
        'total_stream_bytes': sum(x['size'] for x in summary),
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / 'final-report.json').write_text(json.dumps(report, indent=2) + '\n')

    if not args.no_iso:
        make_iso(mkisofs_cmd, disc_root, iso_path, args.volume_id)
        report['iso_bytes'] = iso_path.stat().st_size
        (output_root / 'final-report.json').write_text(json.dumps(report, indent=2) + '\n')

    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
