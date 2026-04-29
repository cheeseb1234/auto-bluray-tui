#!/usr/bin/env python3
from __future__ import annotations

import argparse
import curses
import json
import shutil
import subprocess
import time
import os
import signal
import re
from pathlib import Path

try:
    import pptx_menu_converter
except Exception:
    pptx_menu_converter = None

ENCODERS = ['auto', 'nvenc', 'cpu']
RESOLUTIONS = ['1920x1080', '1280x720']
QUALITIES = [('high', 16), ('default', 18), ('smaller', 21)]
NVENC_PRESETS = ['p4', 'p5', 'p6', 'p7']
AUDIO_BITRATES = ['192k', '256k', '448k', '640k']
DISC_PRESETS = ['dvd5', 'dvd9', 'bd25', 'quality']
DISC_PRESET_LABELS = {
    'dvd5': 'DVD-5 size',
    'dvd9': 'DVD-9 size',
    'bd25': 'BD-25 size',
    'quality': 'Quality/no size cap',
}
DISC_PRESET_CAPACITY = {'dvd5': 4_700_000_000, 'dvd9': 8_500_000_000, 'bd25': 25_000_000_000}
SUPPORTED_VIDEO_EXTS = ('.mp4', '.mkv', '.m2ts', '.mov')

WORKFLOW_STEPS = [
    ('fetch-opensubtitles', 'Fetch missing subtitles'),
    ('analyze', 'Analyze project/media'),
    ('convert-pptx-menu', 'Process menu.pptx'),
    ('get-tsmuxer', 'Check/install tsMuxer'),
    ('prepare-bluray-media', 'Encode Blu-ray media'),
    ('create-bluray-authoring-plan', 'Create authoring plan'),
    ('build-sample-disc', 'Build BD-J menu overlay'),
    ('create-final-bluray-iso', 'Assemble final ISO'),
    ('auto-burn-final-bluray', 'Auto-burn first disc'),
]

COLORS = {}


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
        'audio_bitrate': '448k',
        'disc_title': '',
        'disc_preset': 'bd25',
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


def workflow_dir(project: Path):
    return project / 'build' / 'bluray-workflow'


def workflow_state_path(project: Path):
    return workflow_dir(project) / 'workflow-state.json'


def read_workflow_state(project: Path):
    return read_json(workflow_state_path(project)) or {}


def write_workflow_state(project: Path, state: dict):
    d = workflow_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    workflow_state_path(project).write_text(json.dumps(state, indent=2) + '\n')


def workflow_log_path(project: Path):
    return workflow_dir(project) / 'autopilot.log'


def media_manifest_path(project: Path):
    return project / 'build' / 'bluray-media' / 'media-manifest.json'


def final_iso_path(project: Path):
    return project / 'build' / 'final-bluray' / 'bluray-project.iso'


def video_files(project: Path):
    try:
        return sorted([p for p in project.iterdir() if p.suffix.lower() in SUPPORTED_VIDEO_EXTS], key=lambda p: p.name.lower())
    except Exception:
        return []


def project_input_files(project: Path):
    files = []
    menu = project / 'menu.pptx'
    if menu.exists():
        files.append(menu)
    files.extend(video_files(project))
    try:
        files.extend(sorted([p for p in project.iterdir() if p.suffix.lower() in ('.srt', '.sup', '.ass', '.ssa')], key=lambda p: p.name.lower()))
    except Exception:
        pass
    return files


def manifest_stale_reason(project: Path):
    manifest = media_manifest_path(project)
    if not manifest.exists():
        return 'missing media manifest'
    try:
        manifest_mtime = manifest.stat().st_mtime
        newest = max((p.stat().st_mtime for p in project_input_files(project)), default=0)
        if newest > manifest_mtime + 1:
            return 'project inputs changed since last analysis'
    except Exception:
        return 'could not verify media manifest freshness'
    return ''


def run_initial_analyze(root: Path, project: Path):
    logs = project / 'build' / 'bluray-workflow'
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / 'initial-analyze.log'
    cmd = [str(root / 'scripts' / 'analyze-bluray-project.sh'), str(project)]
    with log_path.open('ab') as log:
        log.write(('\n=== TUI initial analyze {} ===\n'.format(time.strftime('%Y-%m-%d %H:%M:%S'))).encode())
        log.write(('CMD: ' + ' '.join(cmd) + '\n').encode())
        result = subprocess.run(cmd, cwd=str(root), stdout=log, stderr=subprocess.STDOUT)
    return result.returncode, str(log_path)


def project_diagnostics(project: Path, root: Path, rows=None, meta=None, cfg=None):
    """Return practical TUI preflight issues and auto-corrections.

    Keep this lightweight: it parses PPTX XML and existing JSON/log state, but it
    does not run LibreOffice, ffmpeg, muxing, or disc probes.
    """
    rows = rows or []
    meta = meta or {}
    issues = []

    def add(severity, message, fix=''):
        issues.append({'severity': severity, 'message': message, 'fix': fix})

    menu = project / 'menu.pptx'
    vids = video_files(project)
    if not menu.exists():
        add('error', 'Missing menu.pptx in the project folder.', 'Add/export the PowerPoint menu as menu.pptx.')
    if not vids:
        add('error', 'No supported video files found beside menu.pptx.', 'Use .mkv, .mp4, .m2ts, or .mov files in the project folder.')

    normalized = {}
    for p in vids:
        k = pptx_menu_converter.match_key(p.stem) if pptx_menu_converter else re.sub(r'[^a-z0-9]+', ' ', p.stem.lower()).strip()
        normalized.setdefault(k, []).append(p.name)
    dupes = [names for names in normalized.values() if len(names) > 1]
    if dupes:
        add('warning', 'Some video filenames normalize to the same title, which can make button matching ambiguous.', 'Rename one of: ' + '; '.join(', '.join(d) for d in dupes[:3]))

    subtitle_exts = {'.srt', '.sup', '.ass', '.ssa'}
    videos_without_sidecars = []
    for video in vids:
        stem = video.stem.lower()
        has_sidecar = any(p.suffix.lower() in subtitle_exts and p.stem.lower().startswith(stem) for p in project.iterdir())
        if not has_sidecar:
            videos_without_sidecars.append(video.name)
    if videos_without_sidecars and not os.environ.get('OPENSUBTITLES_API_KEY'):
        add('info', 'No sidecar subtitles found for some videos; OpenSubtitles lookup is disabled because OPENSUBTITLES_API_KEY is not set.', 'Set OPENSUBTITLES_API_KEY plus OPENSUBTITLES_USERNAME/PASSWORD to auto-download .srt files.')
    elif videos_without_sidecars:
        add('info', 'Some videos have no sidecar subtitles; autopilot will search OpenSubtitles before analyzing media.', ', '.join(videos_without_sidecars[:6]))

    model = None
    if menu.exists() and vids and pptx_menu_converter:
        try:
            model = pptx_menu_converter.extract_slide_model(menu, project)
            pptx_menu_converter.assign_video_actions(model)
            slides = model.get('slides') or []
            buttons = [b for s in slides for b in s.get('buttons', [])]
            actions = model.get('video_actions') or []
            if not slides:
                add('error', 'menu.pptx contains no slides.', 'Add at least one slide with video buttons.')
            if not buttons:
                add('error', 'No clickable PPTX menu buttons were detected.', 'Use button text that matches a video name or add slide hyperlinks.')
            if not actions:
                add('error', 'No PPTX buttons match any video files.', 'Rename button text to match video filenames; fuzzy/space/punctuation fixes are automatic when safe.')
            loop_targets = {l.get('video_file') for s in slides for l in s.get('loop_videos', [])}
            targets = {a.get('video_file') for a in actions} | loop_targets
            missing_targets = sorted(t for t in targets if t and not (project / t).exists())
            if missing_targets:
                add('error', 'PPTX menu points at video files that are missing.', 'Missing: ' + ', '.join(missing_targets[:6]))
            unused = sorted({p.name for p in vids} - {t for t in targets if t})
            if unused and actions:
                add('warning', 'Some project videos are not reachable from the PPTX menu.', 'Unreferenced: ' + ', '.join(unused[:6]))
            for warn in model.get('match_warnings') or []:
                add('info', warn.get('message', 'Auto-corrected a menu/video filename match.'), 'Review generated video-actions.json if this was unexpected.')
        except Exception as e:
            add('error', f'Could not parse menu.pptx for preflight checks: {e}', 'Open/re-save the PPTX, then retry.')
    elif menu.exists() and vids and not pptx_menu_converter:
        add('warning', 'PPTX preflight parser could not be loaded.', 'Run the converter step to reveal menu issues.')

    for row in rows:
        status = row.get('status')
        if status == 'partial':
            add('error', f'{row.get("file")} appears partially encoded.', 'Re-run encode/autopilot; existing partial outputs will be replaced when needed.')
        elif status == 'oversized':
            add('error', f'{row.get("file")} is too large for the selected disc target.', 'Choose a larger disc target or re-encode with current disc setting.')
        elif status == 'stale':
            add('warning', f'{row.get("file")} has a stale encoder PID.', 'Press k to clear running state, then rerun encode/autopilot.')

    workflow = meta.get('workflow') or read_workflow_state(project)
    if workflow.get('pid') and workflow.get('status') == 'running' and not pid_running(workflow.get('pid')):
        add('warning', f'Autopilot state is stale at step {workflow.get("step")}.', 'The TUI will treat it as stopped; press w to rerun safely.')

    iso = final_iso_path(project)
    report = project / 'build' / 'final-bluray' / 'final-report.json'
    if iso.exists() and menu.exists() and iso.stat().st_mtime < menu.stat().st_mtime:
        add('warning', 'The final ISO is older than menu.pptx.', 'Rebuild the final ISO before burning.')
    if model and report.exists():
        try:
            report_data = read_json(report) or {}
            # Preflight parses the PPTX without regenerating the derived loop
            # videos, so compare only normal button actions here. Loop playlists
            # are validated by the generated playlist map/final report path.
            report_titles = {t.get('video_file') for t in report_data.get('titles', []) if t.get('kind', 'button') == 'button'}
            expected_titles = {a.get('video_file') for a in model.get('video_actions', []) if a.get('kind', 'button') == 'button'}
            if expected_titles and report_titles and report_titles != expected_titles:
                add('warning', 'The final report does not match the current PPTX video button actions.', 'Rebuild final ISO; playlist map may be stale.')
        except Exception:
            pass

    return issues


def blocking_preflight_issues(project: Path, root: Path, cfg: dict):
    issues = project_diagnostics(project, root, [], {}, cfg)
    return [i for i in issues if i.get('severity') == 'error']


def burn_dir(project: Path):
    return project / 'build' / 'bluray-burn'


def burn_state_path(project: Path):
    return burn_dir(project) / 'burn-state.json'


def burn_log_path(project: Path):
    return burn_dir(project) / 'burn.log'


def read_burn_state(project: Path):
    state = read_json(burn_state_path(project)) or {}
    if state.get('pid') and state.get('status') == 'running' and not pid_running(state.get('pid')):
        state = {**state, 'status': 'stale'}
    return state


def write_burn_state(project: Path, state: dict):
    d = burn_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    burn_state_path(project).write_text(json.dumps(state, indent=2) + '\n')


def shell_quote(value):
    return "'" + str(value).replace("'", "'\\''") + "'"


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


def parse_bitrate(value: str|None) -> int:
    if not value:
        return 0
    text = str(value).strip().lower()
    mult = 1
    if text.endswith('k'):
        mult = 1000; text = text[:-1]
    elif text.endswith('m'):
        mult = 1_000_000; text = text[:-1]
    try:
        return int(float(text) * mult)
    except Exception:
        return 0


def preset_audio_bitrate(disc_preset: str):
    return {'dvd5': '192k', 'dvd9': '256k', 'bd25': '448k'}.get(disc_preset)


def estimated_preset_total_bitrate(disc_preset: str, total_duration: float):
    cap = DISC_PRESET_CAPACITY.get(disc_preset)
    if not cap or not total_duration:
        return 0
    audio = parse_bitrate(preset_audio_bitrate(disc_preset))
    video = max(350_000, int(cap * 8 * 0.88 / total_duration - audio - 350_000))
    return int((video + audio + 500_000) * 1.20)


def build_encode_command(root: Path, project: Path, cfg: dict):
    cmd = [str(root / 'scripts' / 'prepare-bluray-media.sh'), str(project)]
    cmd += ['--encoder', cfg['encoder']]
    cmd += ['--resolution', cfg['resolution']]
    q = str(quality_value(cfg))
    cmd += ['--cq', q, '--crf', q]
    cmd += ['--nvenc-preset', cfg['nvenc_preset']]
    cmd += ['--audio-bitrate', cfg['audio_bitrate']]
    cmd += ['--disc-preset', cfg.get('disc_preset', 'bd25')]
    if cfg.get('only'):
        cmd += ['--only', cfg['only']]
    if cfg.get('smoke_seconds'):
        cmd += ['--smoke-seconds', str(cfg['smoke_seconds'])]
    return cmd


def build_workflow_script(root: Path, project: Path, cfg: dict, state_file: Path):
    encode_cmd = ' '.join(shell_quote(x) for x in build_encode_command(root, project, cfg))
    disc_title = (cfg.get('disc_title') or project.name).strip() or project.name
    scripts = root / 'scripts'
    project_q = shell_quote(project)
    state_q = shell_quote(state_file)
    ts_muxer = root / 'tools' / 'bin' / 'tsMuxer'
    # Keep previews out of autopilot: they are interactive GUI launchers, not build steps.
    return f'''set -euo pipefail
ROOT={shell_quote(root)}
PROJECT={project_q}
STATE={state_q}

update_state() {{
python3 - "$STATE" "$1" "$2" <<'PY'
import json, sys, time
from pathlib import Path
path = Path(sys.argv[1])
state = {{}}
if path.exists():
    try:
        state = json.loads(path.read_text())
    except Exception:
        state = {{}}
state.update({{'status': sys.argv[2], 'step': sys.argv[3], 'updated_at': time.time()}})
path.write_text(json.dumps(state, indent=2) + '\\n')
PY
}}

run_step() {{
  local name="$1"; shift
  update_state running "$name"
  echo
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') | $name ==="
  echo "+ $*"
  "$@"
}}

trap 'rc=$?; update_state failed "${{CURRENT_STEP:-unknown}}"; echo "=== WORKFLOW FAILED rc=$rc ==="; exit $rc' ERR

CURRENT_STEP=fetch-opensubtitles
run_step fetch-opensubtitles {shell_quote(scripts / 'fetch-opensubtitles.sh')} "$PROJECT"

CURRENT_STEP=analyze
run_step analyze {shell_quote(scripts / 'analyze-bluray-project.sh')} "$PROJECT"

CURRENT_STEP=convert-pptx-menu
run_step convert-pptx-menu {shell_quote(scripts / 'convert-pptx-menu.sh')} "$PROJECT"
python3 - "$ROOT" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
actions_path = root / 'xlets/grin_samples/Scripts/PptxMenu/video-actions.json'
try:
    actions = json.loads(actions_path.read_text())
except Exception as e:
    raise SystemExit(f'Could not read generated video actions: {{e}}')
button_actions = [a for a in actions if a.get('kind', 'button') == 'button']
if not button_actions:
    raise SystemExit('No PPTX video buttons matched project videos; fix button text or filenames before encoding/burning')
loop_actions = [a for a in actions if a.get('kind') == 'loop']
print(f'Preflight video actions: {{len(button_actions)}} matched button(s); {{len(loop_actions)}} autoplay loop(s)')
PY

if [[ ! -x {shell_quote(ts_muxer)} ]] && ! command -v tsMuxer >/dev/null 2>&1 && ! command -v tsMuxeR >/dev/null 2>&1 && ! command -v tsmuxer >/dev/null 2>&1; then
  CURRENT_STEP=get-tsmuxer
  run_step get-tsmuxer {shell_quote(scripts / 'get-tsmuxer.sh')}
else
  echo
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') | get-tsmuxer ==="
  echo "tsMuxer already available; skipping download"
fi

CURRENT_STEP=prepare-bluray-media
update_state running prepare-bluray-media
echo
echo "=== $(date '+%Y-%m-%d %H:%M:%S') | prepare-bluray-media ==="
echo "+ {encode_cmd}"
{encode_cmd}

CURRENT_STEP=create-bluray-authoring-plan
run_step create-bluray-authoring-plan {shell_quote(scripts / 'create-bluray-authoring-plan.sh')} "$PROJECT"

CURRENT_STEP=build-sample-disc
run_step build-sample-disc {shell_quote(scripts / 'build-sample-disc.sh')}

CURRENT_STEP=create-final-bluray-iso
run_step create-final-bluray-iso {shell_quote(scripts / 'create-final-bluray-iso.sh')} "$PROJECT" --volume-id {shell_quote(disc_title)} --disc-preset {shell_quote(cfg.get('disc_preset', 'bd25'))}

CURRENT_STEP=auto-burn-final-bluray
update_state running auto-burn-final-bluray
echo
echo "=== $(date '+%Y-%m-%d %H:%M:%S') | auto-burn-final-bluray ==="
echo "+ {shell_quote(scripts / 'auto-burn-final-bluray.sh')} $PROJECT"
if {shell_quote(scripts / 'auto-burn-final-bluray.sh')} "$PROJECT"; then
  echo "Automatic burn step complete. Insert another blank disc and press b in the TUI to burn another copy, or press q to exit."
else
  echo "Automatic burn skipped or failed. Use the TUI burner controls after reviewing the message above."
fi

update_state done complete
echo
echo "=== WORKFLOW COMPLETE $(date '+%Y-%m-%d %H:%M:%S') ==="
'''


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


def start_workflow(root: Path, project: Path, cfg: dict):
    save_config(project, cfg)
    d = workflow_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    log_path = workflow_log_path(project)
    state_file = workflow_state_path(project)
    state = {
        'status': 'starting',
        'step': 'starting',
        'started_at': time.time(),
        'updated_at': time.time(),
        'pid': None,
        'log_file': str(log_path),
        'project': str(project),
        'options': cfg,
    }
    write_workflow_state(project, state)
    script = build_workflow_script(root, project, cfg, state_file)
    with log_path.open('ab') as log:
        log.write(('\n=== TUI workflow start {} ===\n'.format(time.strftime('%Y-%m-%d %H:%M:%S'))).encode())
        proc = subprocess.Popen(['bash', '-lc', script], cwd=str(root), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    state['pid'] = proc.pid
    state['status'] = 'running'
    state['step'] = 'starting'
    state['updated_at'] = time.time()
    write_workflow_state(project, state)
    return proc.pid, str(log_path)


def tail_text(path: Path, max_lines=3, max_bytes=12000):
    try:
        with path.open('rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read().decode(errors='ignore')
        lines = data.splitlines()
        return lines[-max_lines:]
    except Exception:
        return []


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


def ffprobe_output_info(path: Path):
    try:
        result = subprocess.run(
            [
                'ffprobe', '-hide_banner', '-v', 'error',
                '-show_entries', 'format=duration,bit_rate:stream=codec_type,codec_name,width,height,sample_rate',
                '-of', 'json', str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            fmt = data.get('format') or {}
            streams = data.get('streams') or []
            video = next((s for s in streams if s.get('codec_type') == 'video'), {})
            audio = next((s for s in streams if s.get('codec_type') == 'audio'), {})
            return {
                'duration': float(fmt.get('duration') or 0),
                'bit_rate': int(fmt.get('bit_rate') or 0),
                'video_codec': video.get('codec_name'),
                'audio_codec': audio.get('codec_name'),
                'width': video.get('width'),
                'height': video.get('height'),
                'sample_rate': audio.get('sample_rate'),
            }
    except Exception:
        pass
    return {}


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


def proc_cmdline(pid):
    try:
        data = Path(f'/proc/{int(pid)}/cmdline').read_bytes()
        return ' '.join(x.decode(errors='ignore') for x in data.split(b'\0') if x)
    except Exception:
        return ''


def proc_pgid(pid):
    try:
        return os.getpgid(int(pid))
    except Exception:
        return None


def stop_pid_group(pid):
    pgid = proc_pgid(pid)
    if not pgid:
        return False, 'process is not running'
    try:
        os.killpg(pgid, signal.SIGTERM)
        return True, f'sent SIGTERM to process group {pgid}'
    except ProcessLookupError:
        return False, 'process is not running'
    except PermissionError:
        return False, f'permission denied stopping process group {pgid}'
    except Exception as e:
        return False, str(e)


def find_running_ffmpeg_for_output(output: Path):
    output_s = str(output)
    proc_root = Path('/proc')
    try:
        pids = [p for p in proc_root.iterdir() if p.name.isdigit()]
    except Exception:
        return None
    for p in pids:
        cmd = proc_cmdline(p.name)
        if 'ffmpeg' in cmd and output_s in cmd:
            try:
                return int(p.name)
            except Exception:
                return None
    return None


def running_rows(rows):
    return [r for r in rows if r.get('pid') and r.get('status') == 'running' and pid_running(r.get('pid'))]


def stop_running_work(project: Path, rows):
    stopped = []
    for row in running_rows(rows):
        ok, msg = stop_pid_group(row.get('pid'))
        stopped.append(f'{row.get("file")}: {msg}')
        state_path = project / 'build' / 'bluray-media' / 'logs' / (row.get('file','').replace('/', '_') + '.state.json')
        state = read_json(state_path) or {}
        state.update({'status': 'stopping' if ok else state.get('status', 'running'), 'stopped_at': time.time(), 'stop_message': msg})
        try:
            state_path.write_text(json.dumps(state, indent=2) + '\n')
        except Exception:
            pass

    workflow = read_workflow_state(project)
    if workflow.get('pid') and workflow.get('status') == 'running' and pid_running(workflow.get('pid')):
        ok, msg = stop_pid_group(workflow.get('pid'))
        stopped.append(f'autopilot: {msg}')
        workflow.update({'status': 'stopping' if ok else workflow.get('status'), 'updated_at': time.time(), 'stop_message': msg})
        write_workflow_state(project, workflow)
    return '; '.join(stopped) if stopped else 'No running encode/autopilot process found.'


def detect_burners():
    burners = []
    for dev in sorted(Path('/dev').glob('sr*')):
        name = dev.name
        model = ''
        vendor = ''
        try:
            model = Path('/sys/block') .joinpath(name, 'device/model').read_text(errors='ignore').strip()
        except Exception:
            pass
        try:
            vendor = Path('/sys/block') .joinpath(name, 'device/vendor').read_text(errors='ignore').strip()
        except Exception:
            pass
        label = ' '.join(x for x in [vendor, model] if x).strip() or name
        burners.append({'device': str(dev), 'label': label})
    return burners


def burn_config_path(project: Path):
    return burn_dir(project) / 'burn-options.json'


def load_burn_config(project: Path):
    return read_json(burn_config_path(project)) or {'device': ''}


def save_burn_config(project: Path, cfg: dict):
    burn_dir(project).mkdir(parents=True, exist_ok=True)
    burn_config_path(project).write_text(json.dumps(cfg, indent=2) + '\n')


def selected_burner(project: Path, burners):
    cfg = load_burn_config(project)
    selected = cfg.get('device')
    devices = [b['device'] for b in burners]
    if selected in devices:
        return selected
    if devices:
        cfg['device'] = devices[0]
        save_burn_config(project, cfg)
        return devices[0]
    return ''


def cycle_burner(project: Path, burners):
    if not burners:
        return ''
    current = selected_burner(project, burners)
    devices = [b['device'] for b in burners]
    next_device = cycle(current, devices)
    save_burn_config(project, {'device': next_device})
    return next_device


def xorriso_tool(root: Path):
    local = root / 'tools' / 'bin' / 'xorriso'
    if local.exists():
        return str(local)
    return shutil.which('xorriso')


def media_capacity_bytes(xorriso: str, device: str):
    try:
        result = subprocess.run(
            [xorriso, '-outdev', device, '-tell_media_space', '-toc'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
        )
        text = result.stdout or ''
        matches = re.findall(r'(?:Media|Free) space\s*:?\s*([0-9]+)s', text, re.IGNORECASE)
        sectors = max([int(m) for m in matches], default=0)
        blankish = bool(re.search(r'Media status\s*:?\s*(is )?(blank|appendable|overwriteable|formatted)', text, re.IGNORECASE))
        return sectors * 2048, blankish, text[-1000:]
    except Exception as e:
        return 0, False, str(e)


def start_burn(root: Path, project: Path, device: str):
    iso = final_iso_path(project)
    if not iso.exists():
        raise RuntimeError(f'Missing ISO: {iso}. Run autopilot first.')
    xorriso = xorriso_tool(root)
    if not xorriso:
        raise RuntimeError('Missing xorriso; install libisoburn/xorriso before burning.')
    if not device:
        raise RuntimeError('No optical burner device detected.')
    capacity, blankish, info = media_capacity_bytes(xorriso, device)
    if capacity < iso.stat().st_size:
        raise RuntimeError(f'Selected disc is too small or unreadable: {human_size(capacity)} available for {human_size(iso.stat().st_size)} ISO.')
    if not blankish:
        raise RuntimeError('Selected burner does not appear to contain blank/appendable/overwriteable media.')
    d = burn_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    log_path = burn_log_path(project)
    state_file = burn_state_path(project)
    state = {
        'status': 'starting',
        'started_at': time.time(),
        'updated_at': time.time(),
        'pid': None,
        'device': device,
        'iso': str(iso),
        'log_file': str(log_path),
    }
    write_burn_state(project, state)
    script = f'''set -euo pipefail
STATE={shell_quote(state_file)}
update_state() {{
python3 - "$STATE" "$1" "$2" <<'PY'
import json, sys, time
from pathlib import Path
path = Path(sys.argv[1])
state = {{}}
if path.exists():
    try:
        state = json.loads(path.read_text())
    except Exception:
        state = {{}}
state.update({{'status': sys.argv[2], 'message': sys.argv[3], 'updated_at': time.time()}})
path.write_text(json.dumps(state, indent=2) + '\\n')
PY
}}
trap 'rc=$?; update_state failed "burn failed rc=$rc"; exit $rc' ERR
update_state running "burning {device}"
{shell_quote(xorriso)} -as cdrecord -v dev={shell_quote(device)} -eject {shell_quote(iso)}
update_state done "burn complete; insert another blank disc and press b again, or press q to exit"
'''
    with log_path.open('ab') as log:
        log.write(('\n=== Burn start {} device={} iso={} ===\n'.format(time.strftime('%Y-%m-%d %H:%M:%S'), device, iso)).encode())
        proc = subprocess.Popen(['bash', '-lc', script], cwd=str(root), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    state['pid'] = proc.pid
    state['status'] = 'running'
    state['message'] = f'burning {device}'
    state['updated_at'] = time.time()
    write_burn_state(project, state)
    return proc.pid, str(log_path)


def stop_burn(project: Path):
    state = read_burn_state(project)
    if state.get('pid') and state.get('status') == 'running' and pid_running(state.get('pid')):
        ok, msg = stop_pid_group(state.get('pid'))
        state.update({'status': 'stopping' if ok else state.get('status'), 'updated_at': time.time(), 'message': msg})
        write_burn_state(project, state)
        return msg
    return 'No running burn process found.'


def collect(project: Path, root: Path):
    media_root = project / 'build' / 'bluray-media'
    manifest = read_json(media_root / 'media-manifest.json')
    cfg = load_config(project)
    if not manifest:
        meta = {'manifest': False, 'media_root': str(media_root)}
        meta['diagnostics'] = project_diagnostics(project, root, [], meta, cfg)
        return [], meta

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
        out_info = {} if raw_status == 'running' else (ffprobe_output_info(out) if out.exists() else {})
        encoded_duration = out_info.get('duration')

        status = raw_status
        pid = state.get('pid')
        if status == 'running' and pid and not pid_running(pid):
            status = 'stale'
        adopted_pid = find_running_ffmpeg_for_output(out)
        if adopted_pid and status != 'running':
            pid = adopted_pid
            status = 'running'
            state = {**state, 'status': 'running', 'pid': adopted_pid, 'adopted_by_tui': True, 'adopted_at': time.time()}
            try:
                (logs / (safe + '.state.json')).write_text(json.dumps(state, indent=2) + '\n')
            except Exception:
                pass
        if status == 'done' and state.get('smoke_seconds'):
            status = 'smoke'
        if status == 'done' and encoded_duration and duration and encoded_duration < duration - 2:
            status = 'partial'
        max_preset_bitrate = estimated_preset_total_bitrate(cfg.get('disc_preset'), sum(float(v.get('duration_seconds') or 0) for v in manifest.get('videos', [])))
        if status == 'done' and max_preset_bitrate and out_info.get('bit_rate') and out_info.get('bit_rate') > max_preset_bitrate:
            status = 'oversized'
        if not status:
            if encoded_duration and duration and encoded_duration >= duration - 2:
                if max_preset_bitrate and out_info.get('bit_rate') and out_info.get('bit_rate') > max_preset_bitrate:
                    status = 'oversized'
                else:
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
            'bit_rate': out_info.get('bit_rate'),
            'progress_seconds': progress_seconds,
            'percent': percent,
            'status': status,
            'pid': pid,
            'adopted_by_tui': state.get('adopted_by_tui'),
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
    workflow = read_workflow_state(project)
    if workflow.get('pid') and workflow.get('status') == 'running' and not pid_running(workflow.get('pid')):
        workflow = {**workflow, 'status': 'stale'}
    burners = detect_burners()
    burn = read_burn_state(project)
    iso = final_iso_path(project)
    meta = {
        'manifest': True, 'media_root': str(media_root), 'tools': tool_status(root),
        'overall_percent': overall_percent, 'done_count': done_count, 'total_count': len(rows),
        'workflow': workflow, 'burners': burners, 'selected_burner': selected_burner(project, burners),
        'burn': burn, 'final_iso': str(iso), 'final_iso_exists': iso.exists(),
        'final_iso_size': iso.stat().st_size if iso.exists() else None,
    }
    meta['diagnostics'] = project_diagnostics(project, root, rows, meta, cfg)
    return rows, meta


def bar(width: int, percent):
    inner = max(1, width - 2)
    if percent is None:
        return '[' + ' ' * inner + ']'
    if percent >= 99.9:
        percent = 100.0
    filled = int(round(inner * percent / 100))
    filled = max(0, min(inner, filled))
    return '[' + '#' * filled + '-' * (inner - filled) + ']'


def init_colors():
    global COLORS
    if COLORS:
        return
    COLORS = {'normal': curses.A_NORMAL, 'bold': curses.A_BOLD}
    try:
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            pairs = [
                ('ok', curses.COLOR_GREEN),
                ('warn', curses.COLOR_YELLOW),
                ('bad', curses.COLOR_RED),
                ('info', curses.COLOR_CYAN),
                ('dim', curses.COLOR_BLUE),
                ('accent', curses.COLOR_MAGENTA),
            ]
            for idx, (name, fg) in enumerate(pairs, start=1):
                curses.init_pair(idx, fg, -1)
                COLORS[name] = curses.color_pair(idx)
                COLORS[name + '_bold'] = curses.color_pair(idx) | curses.A_BOLD
    except curses.error:
        pass


def color(name, fallback=curses.A_NORMAL):
    return COLORS.get(name, fallback)


def status_attr(status):
    if status in ('done', 'complete'):
        return color('ok_bold', curses.A_BOLD)
    if status in ('running', 'starting', 'stopping'):
        return color('info_bold', curses.A_BOLD)
    if status in ('failed', 'oversized'):
        return color('bad_bold', curses.A_BOLD)
    if status in ('partial', 'smoke', 'stale'):
        return color('warn_bold', curses.A_BOLD)
    return curses.A_NORMAL


def diagnostic_attr(severity):
    if severity == 'error':
        return color('bad_bold', curses.A_BOLD)
    if severity == 'warning':
        return color('warn_bold', curses.A_BOLD)
    return color('info')


def draw_diagnostics(stdscr, y, width, diagnostics, max_rows=5):
    if not diagnostics:
        safe_add(stdscr, y, 0, 'Preflight: ok - naming/menu/navigation/ISO checks passed', width - 1, color('ok'))
        return y + 1
    errors = sum(1 for i in diagnostics if i.get('severity') == 'error')
    warnings = sum(1 for i in diagnostics if i.get('severity') == 'warning')
    safe_add(stdscr, y, 0, f'Preflight: {errors} error(s), {warnings} warning(s)  (autocorrect handles safe naming, hitbox, navigation-grid, slide-count, stale-map issues)', width - 1, color('bad_bold' if errors else 'warn_bold'))
    y += 1
    for issue in diagnostics[:max_rows]:
        msg = issue.get('message', '')
        fix = issue.get('fix') or ''
        text = f'  {issue.get("severity", "info")}: {msg}' + (f' | {fix}' if fix else '')
        safe_add(stdscr, y, 0, text, width - 1, diagnostic_attr(issue.get('severity')))
        y += 1
    if len(diagnostics) > max_rows:
        safe_add(stdscr, y, 0, f'  ... {len(diagnostics) - max_rows} more preflight item(s)', width - 1, color('dim'))
        y += 1
    return y


def draw_controls(stdscr, y, width):
    lines = [
        'Actions: w Full autopilot (subtitles -> encode -> ISO -> burn) | Enter Encode media only | b Burn ISO | k Stop work | q Quit',
        'View: r Refresh | v Cycle burner',
        'Options: d Disc size | e Encoder | z Resolution | l Quality | p NVENC preset | a Audio | o Only one video | s Smoke test',
    ]
    for i, line in enumerate(lines):
        safe_add(stdscr, y + i, 0, line, width - 1, color('dim') if i else curses.A_NORMAL)
    return y + len(lines)


def workflow_step_rows(workflow: dict, meta: dict):
    current = workflow.get('step') or ''
    status = workflow.get('status') or ''
    if status == 'done' or current == 'complete':
        current_index = len(WORKFLOW_STEPS)
    else:
        current_index = next((i for i, (key, _) in enumerate(WORKFLOW_STEPS) if key == current), -1)
    rows = []
    for i, (key, label) in enumerate(WORKFLOW_STEPS):
        if status == 'failed' and key == current:
            step_status = 'failed'
            pct = None
        elif i < current_index or status == 'done':
            step_status = 'done'
            pct = 100.0
        elif i == current_index:
            step_status = 'running'
            if key == 'prepare-bluray-media':
                pct = meta.get('overall_percent')
            elif key == 'create-final-bluray-iso' and meta.get('final_iso_exists'):
                pct = 100.0
            else:
                pct = None
        else:
            step_status = 'pending'
            pct = 0.0
        rows.append({'key': key, 'label': label, 'status': step_status, 'percent': pct})
    return rows


def prompt_disc_title(stdscr, project: Path, cfg: dict):
    """Ask at TUI startup for the disc title / ISO volume label."""
    default = (cfg.get('disc_title') or '').strip() or project.name or 'Blu-ray Project'
    try:
        stdscr.nodelay(False)
        curses.echo()
        curses.curs_set(1)
    except curses.error:
        pass
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    safe_width = max(20, width - 4)
    safe_add(stdscr, 1, 2, 'Auto Blu-ray TUI setup', safe_width, color('accent_bold', curses.A_BOLD))
    safe_add(stdscr, 3, 2, 'Enter disc name / title for this Blu-ray.', safe_width)
    safe_add(stdscr, 4, 2, 'This becomes the ISO/UDF volume label; blank uses the project folder name.', safe_width, color('dim'))
    prompt = f'Disc title [{default}]: '
    safe_add(stdscr, 6, 2, prompt, safe_width, color('info_bold', curses.A_BOLD))
    stdscr.refresh()
    try:
        raw = stdscr.getstr(6, 2 + len(prompt), max(1, min(64, width - len(prompt) - 4)))
        title = raw.decode(errors='ignore').strip()
    except Exception:
        title = ''
    cfg['disc_title'] = title or default
    save_config(project, cfg)
    try:
        curses.noecho()
        curses.curs_set(0)
        stdscr.nodelay(True)
    except curses.error:
        pass
    return cfg


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
    init_colors()
    cfg = load_config(project)
    cfg = prompt_disc_title(stdscr, project, cfg)
    stdscr.nodelay(True)
    message = ''
    reason = manifest_stale_reason(project)
    if reason:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        safe_add(stdscr, 1, 2, 'Analyzing project/media before showing the dashboard...', max(20, width - 4), color('info_bold', curses.A_BOLD))
        safe_add(stdscr, 3, 2, f'Reason: {reason}', max(20, width - 4), color('dim'))
        safe_add(stdscr, 5, 2, 'This gives you the video/subtitle inventory before choosing autopilot or encode-only.', max(20, width - 4))
        stdscr.refresh()
        rc, log = run_initial_analyze(root, project)
        message = f'Initial analysis complete; log {log}' if rc == 0 else f'Initial analysis failed rc={rc}; log {log}'
    while True:
        rows, meta = collect(project, root)
        height, width = stdscr.getmaxyx()
        stdscr.erase()
        y = 0
        safe_add(stdscr, y, 0, f'Blu-ray Project Monitor | {project}', width - 1, color('accent_bold', curses.A_BOLD))
        y += 1
        y = draw_controls(stdscr, y, width)
        y += 1

        if not meta.get('manifest'):
            safe_add(stdscr, y, 0, 'No media manifest yet. Initial analysis should have run; press r to retry display or w for full autopilot.', width - 1, color('warn_bold', curses.A_BOLD))
            y += 1
            y = draw_diagnostics(stdscr, y, width, meta.get('diagnostics') or [], max_rows=6)
            workflow = read_workflow_state(project)
            if workflow:
                safe_add(stdscr, y, 0, f'Autopilot: {workflow.get("status", "-")} step={workflow.get("step", "-")} pid={workflow.get("pid") or "-"} log={workflow.get("log_file", workflow_log_path(project))}', width - 1)
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord('q'), ord('Q')):
                return
            if key in (ord('r'), ord('R')):
                rc, log = run_initial_analyze(root, project)
                message = f'Initial analysis complete; log {log}' if rc == 0 else f'Initial analysis failed rc={rc}; log {log}'
            if key in (ord('w'), ord('W')):
                workflow = read_workflow_state(project)
                blockers = blocking_preflight_issues(project, root, cfg)
                if blockers:
                    message = 'Preflight blocked autopilot: ' + blockers[0].get('message', 'fix project inputs first')
                elif workflow.get('pid') and workflow.get('status') == 'running' and pid_running(workflow.get('pid')):
                    message = f'Autopilot already running PID {workflow.get("pid")}; log {workflow.get("log_file")}'
                else:
                    try:
                        pid, log = start_workflow(root, project, cfg)
                        message = f'Started autopilot PID {pid}; log {log}'
                    except Exception as e:
                        message = f'Failed to start autopilot: {e}'
            if key in (ord('k'), ord('K')):
                message = stop_running_work(project, [])
            time.sleep(1)
            continue

        tools = meta.get('tools', {})
        gpu = tools.get('nvidia')
        simple_tools = {k:v for k,v in tools.items() if k != 'nvidia'}
        missing = [k for k, v in simple_tools.items() if not v]
        safe_add(stdscr, y, 0, 'Tools: ' + '  '.join(f'{k}: {"ok" if v else "missing"}' for k, v in simple_tools.items()), width - 1, color('bad_bold' if missing else 'ok'))
        y += 1
        safe_add(stdscr, y, 0, 'GPU: ' + (gpu or 'NVIDIA/NVENC unavailable'), width - 1, color('ok' if gpu else 'warn_bold'))
        y += 1
        overall = meta.get('overall_percent')
        overall_text = f'{overall:5.1f}%' if overall is not None else '  ---%'
        safe_add(stdscr, y, 0, f'Overall: {overall_text}  {meta.get("done_count",0)}/{meta.get("total_count",0)} done  {bar(30, overall)}', width - 1, color('ok_bold' if meta.get('done_count') == meta.get('total_count') else 'info_bold', curses.A_BOLD))
        y += 1
        disc_label = DISC_PRESET_LABELS.get(cfg.get('disc_preset'), cfg.get('disc_preset', 'bd25'))
        opt_attr = color('warn' if cfg.get('disc_preset') == 'quality' else 'ok')
        safe_add(stdscr, y, 0, f'Title: {cfg.get("disc_title") or project.name} | Options: disc={disc_label} encoder={cfg["encoder"]} resolution={cfg["resolution"]} quality={cfg["quality"]} nvenc_preset={cfg["nvenc_preset"]} audio={cfg["audio_bitrate"]} only={cfg.get("only") or "all"} smoke={cfg.get("smoke_seconds") or "off"}', width - 1, opt_attr)
        y += 1
        y = draw_diagnostics(stdscr, y, width, meta.get('diagnostics') or [], max_rows=4)
        workflow = meta.get('workflow') or read_workflow_state(project)
        if workflow:
            w_status = workflow.get('status', '-')
            w_step = workflow.get('step', '-')
            w_pid = workflow.get('pid') or '-'
            safe_add(stdscr, y, 0, f'Autopilot: {w_status} step={w_step} pid={w_pid} log={workflow.get("log_file", workflow_log_path(project))}', width - 1, status_attr(w_status))
            y += 1
            safe_add(stdscr, y, 0, 'Autopilot steps:', width - 1, color('accent_bold', curses.A_BOLD))
            y += 1
            step_bar_width = max(10, min(20, width - 60))
            for step in workflow_step_rows(workflow, meta):
                if y >= height - 10:
                    break
                pct = step['percent']
                pct_text = f'{pct:5.1f}%' if pct is not None else '  ...%'
                safe_add(stdscr, y, 2, f'{step["status"][:7]:<7} {pct_text} {bar(step_bar_width, pct)} {step["label"]}', width - 3, status_attr(step['status']))
                y += 1
            for line in tail_text(Path(workflow.get('log_file') or workflow_log_path(project)), 2):
                safe_add(stdscr, y, 0, '    ' + line, width - 1, color('dim'))
                y += 1
        iso_text = f'ISO: {meta.get("final_iso")} ({human_size(meta.get("final_iso_size"))})' if meta.get('final_iso_exists') else f'ISO: not ready ({meta.get("final_iso")})'
        safe_add(stdscr, y, 0, iso_text, width - 1, color('ok_bold' if meta.get('final_iso_exists') else 'warn_bold', curses.A_BOLD if meta.get('final_iso_exists') else curses.A_NORMAL))
        y += 1
        burners = meta.get('burners') or []
        selected = meta.get('selected_burner') or '-'
        selected_label = next((b.get('label') for b in burners if b.get('device') == selected), 'no optical burner detected')
        safe_add(stdscr, y, 0, f'Burner: {selected} {selected_label}  (v cycle, b burn ISO)', width - 1, color('ok' if burners else 'warn_bold'))
        y += 1
        burn = meta.get('burn') or {}
        if burn:
            b_status = burn.get('status', '-')
            safe_add(stdscr, y, 0, f'Burn: {b_status} device={burn.get("device", "-")} pid={burn.get("pid") or "-"} {burn.get("message", "")} log={burn.get("log_file", burn_log_path(project))}', width - 1, status_attr(b_status))
            y += 1
            for line in tail_text(Path(burn.get('log_file') or burn_log_path(project)), 2):
                safe_add(stdscr, y, 0, '    ' + line, width - 1, color('dim'))
                y += 1
        if message:
            safe_add(stdscr, y, 0, message, width - 1, color('info_bold', curses.A_BOLD))
        y += 2

        bar_width = max(18, min(34, width - 76))
        header = '{:<16} {:<9} {:>7} {:>10} {:>10} {:>8} {}'.format('File', 'Status', 'Pct', 'Encoded', 'Duration', 'Size', 'Progress')
        safe_add(stdscr, y, 0, header, width - 1, curses.A_UNDERLINE | color('accent'))
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
            attr = status_attr(row['status'])
            safe_add(stdscr, y, 0, line, width - 1, attr)
            y += 1
            detail = '    enc={} fps={} speed={} bitrate={} output={}'.format(row.get('encoder') or '-', row['fps'] or '-', row['speed'] or '-', row['bitrate'] or '-', row['output'])
            safe_add(stdscr, y, 0, detail, width - 1, color('dim'))
            y += 1

        y = height - 2
        safe_add(stdscr, y, 0, f'Updated {time.strftime("%H:%M:%S")}', width - 1, color('dim'))
        stdscr.refresh()
        for _ in range(10):
            key = stdscr.getch()
            if key in (ord('q'), ord('Q')):
                save_config(project, cfg)
                return
            if key in (ord('r'), ord('R')):
                reason = manifest_stale_reason(project)
                if reason:
                    rc, log = run_initial_analyze(root, project)
                    message = f'Re-analysis complete; log {log}' if rc == 0 else f'Re-analysis failed rc={rc}; log {log}'
                else:
                    message = 'Refreshed; media analysis is current.'
                break
            if key in (10, 13):
                if running_rows(rows):
                    message = 'Encode already running; TUI has control. Press k to stop it first.'
                else:
                    try:
                        pid, log = start_encode(root, project, cfg)
                        message = f'Started encode PID {pid}; log {log}'
                    except Exception as e:
                        message = f'Failed to start encode: {e}'
                break
            if key in (ord('w'), ord('W')):
                workflow = read_workflow_state(project)
                blockers = blocking_preflight_issues(project, root, cfg)
                if running_rows(rows):
                    message = 'Encode already running; TUI has control. Press k to stop it first.'
                elif blockers:
                    message = 'Preflight blocked autopilot: ' + blockers[0].get('message', 'fix project inputs first')
                elif workflow.get('pid') and workflow.get('status') == 'running' and pid_running(workflow.get('pid')):
                    message = f'Autopilot already running PID {workflow.get("pid")}; log {workflow.get("log_file")}'
                else:
                    try:
                        pid, log = start_workflow(root, project, cfg)
                        message = f'Started autopilot PID {pid}; log {log}'
                    except Exception as e:
                        message = f'Failed to start autopilot: {e}'
                break
            if key in (ord('k'), ord('K')):
                msg1 = stop_running_work(project, rows)
                msg2 = stop_burn(project)
                message = msg1 if msg2.startswith('No running') else (msg1 + '; ' + msg2)
                break
            if key in (ord('v'), ord('V')):
                device = cycle_burner(project, meta.get('burners') or detect_burners())
                message = f'Selected burner {device}' if device else 'No optical burner detected.'
                break
            if key in (ord('b'), ord('B')):
                burn = read_burn_state(project)
                if burn.get('pid') and burn.get('status') == 'running' and pid_running(burn.get('pid')):
                    message = f'Burn already running PID {burn.get("pid")}; log {burn.get("log_file")}'
                elif running_rows(rows):
                    message = 'Encode is still running. Wait for ISO creation before burning.'
                else:
                    try:
                        burners = meta.get('burners') or detect_burners()
                        device = selected_burner(project, burners)
                        pid, log = start_burn(root, project, device)
                        message = f'Started burn PID {pid} on {device}; log {log}'
                    except Exception as e:
                        message = f'Failed to start burn: {e}'
                break
            if key in (ord('d'), ord('D')):
                cfg['disc_preset'] = cycle(cfg.get('disc_preset','bd25'), DISC_PRESETS)
                preset_audio = preset_audio_bitrate(cfg['disc_preset'])
                if preset_audio:
                    cfg['audio_bitrate'] = preset_audio
                save_config(project, cfg); break
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
