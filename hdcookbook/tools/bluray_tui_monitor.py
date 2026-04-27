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

    return rows, {'manifest': True, 'media_root': str(media_root), 'tools': tool_status(root)}


def bar(width: int, percent):
    inner = max(1, width - 2)
    if percent is None:
        return '[' + ' ' * inner + ']'
    filled = int(inner * percent / 100)
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
    while True:
        rows, meta = collect(project, root)
        height, width = stdscr.getmaxyx()
        stdscr.erase()
        y = 0
        safe_add(stdscr, y, 0, f'Blu-ray Project Monitor | {project}', width - 1, curses.A_BOLD)
        y += 1
        safe_add(stdscr, y, 0, 'q quit | r refresh | run encode separately: ./scripts/prepare-bluray-media.sh "{}"'.format(project), width - 1)
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
        y += 2

        bar_width = max(18, min(34, width - 76))
        header = '{:<16} {:<9} {:>7} {:>10} {:>10} {:>8} {}'.format('File', 'Status', 'Pct', 'Encoded', 'Duration', 'Size', 'Progress')
        safe_add(stdscr, y, 0, header, width - 1, curses.A_UNDERLINE)
        y += 1

        for row in rows:
            if y >= height - 3:
                break
            pct = row['percent']
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
                return
            if key in (ord('r'), ord('R')):
                break
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
