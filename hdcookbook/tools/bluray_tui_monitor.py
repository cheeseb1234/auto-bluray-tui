#!/usr/bin/env python3
from __future__ import annotations

import argparse
import curses
import json
import shutil
import subprocess
import time
import os
from pathlib import Path

ENCODERS = ['auto', 'nvenc', 'cpu']
RESOLUTIONS = ['1920x1080', '1280x720']
QUALITIES = [('high', 16), ('default', 18), ('smaller', 21)]
NVENC_PRESETS = ['p4', 'p5', 'p6', 'p7']
AUDIO_BITRATES = ['448k', '640k']


def human_time(sec):
    if sec is None:
        return '--:--:--'
    sec = max(0, int(sec))
    return f'{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d}'


def human_size(n):
    if n is None:
        return '-'
    n = float(n)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if n < 1024 or unit == 'TB':
            return f'{n:.1f}{unit}'
        n /= 1024


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None




def config_path(project: Path):
    return project / 'build' / 'bluray-media' / 'encode-options.json'


def default_config():
    return {
        'encoder': 'auto',
        'resolution': '1920x1080',
        'quality': 'default',
        'nvenc_preset': 'p5',
        'audio_bitrate': '640k',
        'only': '',
        'smoke_seconds': '',
    }


def load_config(project: Path):
    cfg = default_config()
    saved = read_json(config_path(project)) or {}
    cfg.update({k: v for k, v in saved.items() if k in cfg})
    return cfg


def save_config(project: Path, cfg: dict):
    path = config_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + '\n')


def cycle(value, choices, step=1):
    try:
        i = choices.index(value)
    except ValueError:
        i = 0
    return choices[(i + step) % len(choices)]


def quality_value(cfg):
    for name, value in QUALITIES:
        if name == cfg.get('quality'):
            return value
    return 18


def build_encode_command(root: Path, project: Path, cfg: dict):
    cmd = [str(root / 'scripts' / 'prepare-bluray-media.sh'), str(project)]
    cmd += ['--encoder', cfg['encoder']]
    cmd += ['--resolution', cfg['resolution']]
    q = str(quality_value(cfg))
    cmd += ['--cq', q, '--crf', q]
    cmd += ['--nvenc-preset', cfg['nvenc_preset']]
    cmd += ['--audio-bitrate', cfg['audio_bitrate']]
    if cfg.get('only'):
        cmd += ['--only', cfg['only']]
    if cfg.get('smoke_seconds'):
        cmd += ['--smoke-seconds', str(cfg['smoke_seconds'])]
    return cmd


def start_encode(root: Path, project: Path, cfg: dict):
    save_config(project, cfg)
    logs = project / 'build' / 'bluray-media' / 'logs'
    logs.mkdir(parents=True, exist_ok=True)
    control_log = logs / 'tui-started-encode.log'
    cmd = build_encode_command(root, project, cfg)
    with control_log.open('ab') as log:
        log.write(('\n=== TUI start {} ===\n'.format(time.strftime('%Y-%m-%d %H:%M:%S'))).encode())
        log.write(('CMD: ' + ' '.join(cmd) + '\n').encode())
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return proc.pid, str(control_log)


def read_progress(path: Path):
    data = {}
    try:
        for line in path.read_text(errors='ignore').splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                data[key] = value
    except Exception:
        pass
    return data


def ffprobe_duration(path: Path):
    try:
        result = subprocess.run(
            [
                'ffprobe', '-hide_banner', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return None


def nvidia_summary():
    try:
        smi = subprocess.run(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
        enc = subprocess.run(['ffmpeg','-hide_banner','-encoders'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5)
        if smi.returncode == 0 and 'h264_nvenc' in enc.stdout:
            return smi.stdout.strip()
    except Exception:
        pass
    return None


def tool_status(root: Path):
    def find_tool(name: str):
        local = root / 'tools' / 'bin' / name
        if local.exists():
            return str(local)
        return shutil.which(name)

    return {
        'ffmpeg': find_tool('ffmpeg'),
        'ffprobe': find_tool('ffprobe'),
        'tsMuxer': find_tool('tsMuxer') or find_tool('tsMuxeR') or find_tool('tsmuxer'),
        'xorriso': find_tool('xorriso'),
        'nvidia': nvidia_summary(),
    }


def pid_running(pid):
    try:
        return bool(pid) and Path(f'/proc/{int(pid)}').exists()
    except Exception:
        return False


def collect(project: Path, root: Path):
    media_root = project / 'build' / 'bluray-media'
    manifest = read_json(media_root / 'media-manifest.json')
    if not manifest:
        return [], {'manifest': False, 'media_root': str(media_root)}

    rows = []
    for item in manifest.get('videos', []):
        out = media_root / item['recommended_output']
        logs = media_root / 'logs'
        safe = item['file'].replace('/', '_')
        state = read_json(logs / (safe + '.state.json')) or {}
        prog = read_progress(logs / (safe + '.progress'))
        duration = float(item.get('duration_seconds') or 0)

        try:
            out_time_ms = int(prog.get('out_time_ms', '0'))
        except Exception:
            out_time_ms = 0
        progress_seconds = out_time_ms / 1_000_000 if out_time_ms else None
        raw_status = state.get('status')
        # Avoid probing a file that ffmpeg is actively writing; progress output is faster
        # and avoids flaky reads of a growing transport stream.
        encoded_duration = None if raw_status == 'running' else (ffprobe_duration(out) if out.exists() else None)

        status = raw_status
        if status == 'running' and state.get('pid') and not pid_running(state.get('pid')):
            status = 'stale'
        if status == 'done' and state.get('smoke_seconds'):
            status = 'smoke'
        if status == 'done' and encoded_duration and duration and encoded_duration < duration - 2:
            status = 'partial'
        if not status:
            if encoded_duration and duration and encoded_duration >= duration - 2:
                status = 'done'
            elif encoded_duration:
                status = 'partial'
            else:
                status = 'pending'

        basis = progress_seconds or encoded_duration
        percent = min(100.0, basis / duration * 100) if duration and basis else None
        rows.append({
            'file': item['file'],
            'duration': duration,
            'output': out,
            'output_exists': out.exists(),
            'size': out.stat().st_size if out.exists() else None,
            'encoded_duration': encoded_duration,
            'progress_seconds': progress_seconds,
            'percent': percent,
            'status': status,
            'pid': state.get('pid'),
            'smoke_seconds': state.get('smoke_seconds'),
            'speed': prog.get('speed', ''),
            'encoder': state.get('encoder', ''),
            'fps': prog.get('fps', ''),
            'bitrate': prog.get('bitrate', ''),
        })

    total_duration = sum(float(r.get('duration') or 0) for r in rows)
    total_done = sum(float((r.get('progress_seconds') or r.get('encoded_duration') or 0)) for r in rows)
    overall_percent = min(100.0, total_done / total_duration * 100) if total_duration else None
    done_count = sum(1 for r in rows if r.get('status') == 'done')
    return rows, {'manifest': True, 'media_root': str(media_root), 'tools': tool_status(root), 'overall_percent': overall_percent, 'done_count': done_count, 'total_count': len(rows)}


def bar(width: int, percent):
    inner = max(1, width - 2)
    if percent is None:
        return '[' + ' ' * inner + ']'
    if percent >= 99.9:
        percent = 100.0
    filled = int(round(inner * percent / 100))
    filled = max(0, min(inner, filled))
    return '[' + '#' * filled + '-' * (inner - filled) + ']'


def safe_add(stdscr, y, x, text, width, attr=curses.A_NORMAL):
    try:
        if y < 0 or x < 0:
            return
        max_y, max_x = stdscr.getmaxyx()
        if y >= max_y or x >= max_x:
            return
        stdscr.addnstr(y, x, str(text), max(0, min(width, max_x - x - 1)), attr)
    except curses.error:
        pass


def draw(stdscr, project: Path, root: Path):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.nodelay(True)
    cfg = load_config(project)
    message = ''
    while True:
        rows, meta = collect(project, root)
        height, width = stdscr.getmaxyx()
        stdscr.erase()
        y = 0
        safe_add(stdscr, y, 0, f'Blu-ray Project Monitor | {project}', width - 1, curses.A_BOLD)
        y += 1
        safe_add(stdscr, y, 0, 'q quit | r refresh | ENTER start | e encoder | z resolution | l quality | p preset | a audio | o only | s smoke', width - 1)
        y += 2

        if not meta.get('manifest'):
            safe_add(stdscr, y, 0, 'No media manifest yet. Run ./scripts/analyze-bluray-project.sh first.', width - 1, curses.A_BOLD)
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord('q'), ord('Q')):
                return
            time.sleep(1)
            continue

        tools = meta.get('tools', {})
        gpu = tools.get('nvidia')
        simple_tools = {k:v for k,v in tools.items() if k != 'nvidia'}
        safe_add(stdscr, y, 0, 'Tools: ' + '  '.join(f'{k}: {"ok" if v else "missing"}' for k, v in simple_tools.items()), width - 1)
        y += 1
        safe_add(stdscr, y, 0, 'GPU: ' + (gpu or 'NVIDIA/NVENC unavailable'), width - 1)
        y += 1
        overall = meta.get('overall_percent')
        overall_text = f'{overall:5.1f}%' if overall is not None else '  ---%'
        safe_add(stdscr, y, 0, f'Overall: {overall_text}  {meta.get("done_count",0)}/{meta.get("total_count",0)} done  {bar(30, overall)}', width - 1, curses.A_BOLD)
        y += 1
        safe_add(stdscr, y, 0, f'Options: encoder={cfg["encoder"]} resolution={cfg["resolution"]} quality={cfg["quality"]} nvenc_preset={cfg["nvenc_preset"]} audio={cfg["audio_bitrate"]} only={cfg.get("only") or "all"} smoke={cfg.get("smoke_seconds") or "off"}', width - 1)
        y += 1
        if message:
            safe_add(stdscr, y, 0, message, width - 1, curses.A_BOLD)
        y += 2

        bar_width = max(18, min(34, width - 76))
        header = '{:<16} {:<9} {:>7} {:>10} {:>10} {:>8} {}'.format('File', 'Status', 'Pct', 'Encoded', 'Duration', 'Size', 'Progress')
        safe_add(stdscr, y, 0, header, width - 1, curses.A_UNDERLINE)
        y += 1

        for row in rows:
            if y >= height - 3:
                break
            pct = 100.0 if row.get('status') == 'done' else row['percent']
            pct_text = f'{pct:5.1f}%' if pct is not None else '  ---%'
            encoded = human_time(row['progress_seconds'] or row['encoded_duration'])
            duration = human_time(row['duration'])
            size = human_size(row['size'])
            line = '{:<16} {:<9} {:>7} {:>10} {:>10} {:>8} {}'.format(
                row['file'][:16], row['status'][:9], pct_text, encoded, duration, size, bar(bar_width, pct)
            )
            attr = curses.A_NORMAL
            if row['status'] == 'failed':
                attr = curses.A_BOLD
            elif row['status'] in ('running', 'done'):
                attr = curses.A_BOLD
            safe_add(stdscr, y, 0, line, width - 1, attr)
            y += 1
            detail = '    enc={} fps={} speed={} bitrate={} output={}'.format(row.get('encoder') or '-', row['fps'] or '-', row['speed'] or '-', row['bitrate'] or '-', row['output'])
            safe_add(stdscr, y, 0, detail, width - 1)
            y += 1

        y = height - 2
        safe_add(stdscr, y, 0, f'Updated {time.strftime("%H:%M:%S")}', width - 1)
        stdscr.refresh()
        for _ in range(10):
            key = stdscr.getch()
            if key in (ord('q'), ord('Q')):
                save_config(project, cfg)
                return
            if key in (ord('r'), ord('R')):
                break
            if key in (10, 13):
                try:
                    pid, log = start_encode(root, project, cfg)
                    message = f'Started encode PID {pid}; log {log}'
                except Exception as e:
                    message = f'Failed to start encode: {e}'
                break
            if key in (ord('e'), ord('E')):
                cfg['encoder'] = cycle(cfg['encoder'], ENCODERS)
                save_config(project, cfg); break
            if key in (ord('z'), ord('Z')):
                cfg['resolution'] = cycle(cfg['resolution'], RESOLUTIONS)
                save_config(project, cfg); break
            if key in (ord('l'), ord('L')):
                cfg['quality'] = cycle(cfg['quality'], [q[0] for q in QUALITIES])
                save_config(project, cfg); break
            if key in (ord('p'), ord('P')):
                cfg['nvenc_preset'] = cycle(cfg['nvenc_preset'], NVENC_PRESETS)
                save_config(project, cfg); break
            if key in (ord('a'), ord('A')):
                cfg['audio_bitrate'] = cycle(cfg['audio_bitrate'], AUDIO_BITRATES)
                save_config(project, cfg); break
            if key in (ord('o'), ord('O')):
                onlys = ['', 'Video 1', 'Video 2', 'Video 3', 'Video 4']
                cfg['only'] = cycle(cfg.get('only',''), onlys)
                save_config(project, cfg); break
            if key in (ord('s'), ord('S')):
                smokes = ['', '5', '30', '120']
                cfg['smoke_seconds'] = cycle(str(cfg.get('smoke_seconds') or ''), smokes)
                save_config(project, cfg); break
            time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description='Curses monitor for Blu-ray media preparation progress.')
    parser.add_argument('project_dir', nargs='?', default='/home/corey/.openclaw/Bluray project')
    parser.add_argument('--once', action='store_true', help='print a noninteractive status snapshot')
    args = parser.parse_args()
    project = Path(args.project_dir).resolve()
    root = Path(__file__).resolve().parents[1]

    if args.once:
        rows, meta = collect(project, root)
        print(json.dumps({'project': str(project), 'meta': meta, 'videos': rows}, default=str, indent=2))
        return

    curses.wrapper(draw, project, root)


if __name__ == '__main__':
    main()
