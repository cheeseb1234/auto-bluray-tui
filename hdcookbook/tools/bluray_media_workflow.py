#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, os, shlex, subprocess, sys, time
from pathlib import Path

VIDEO_EXTS={'.mkv','.mp4','.m2ts','.mov'}
SUB_EXTS={'.srt','.sup','.ass','.ssa'}


def run(cmd):
    return subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout


def ffprobe(path: Path):
    data=run(['ffprobe','-hide_banner','-v','error','-show_entries',
              'format=filename,duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,channels,sample_rate:stream_tags=language,title',
              '-of','json',str(path)])
    return json.loads(data)


def language_from_name(path: Path):
    s=path.stem.lower()
    if 'spanish' in s or ' esp' in s or '.es' in s:
        return 'spa'
    if 'english' in s or ' eng' in s or '.en' in s:
        return 'eng'
    return 'eng'


def discover(project: Path):
    videos=sorted([p for p in project.iterdir() if p.suffix.lower() in VIDEO_EXTS], key=lambda p:p.name.lower())
    subs=sorted([p for p in project.iterdir() if p.suffix.lower() in SUB_EXTS], key=lambda p:p.name.lower())
    items=[]
    for v in videos:
        probe=ffprobe(v)
        vstreams=[s for s in probe.get('streams',[]) if s.get('codec_type')=='video']
        astreams=[s for s in probe.get('streams',[]) if s.get('codec_type')=='audio']
        sstreams=[s for s in probe.get('streams',[]) if s.get('codec_type')=='subtitle']
        matching_subs=[]
        for s in subs:
            # Match "Video 4.srt" and "Video 4 Spanish.srt" to "Video 4.mp4".
            if s.stem.lower().startswith(v.stem.lower()):
                matching_subs.append({'file':s.name,'language':language_from_name(s)})
        item={
            'file': v.name,
            'duration_seconds': float(probe.get('format',{}).get('duration') or 0),
            'size_bytes': int(probe.get('format',{}).get('size') or 0),
            'video': vstreams[0] if vstreams else None,
            'audio': astreams[0] if astreams else None,
            'embedded_subtitle_streams': sstreams,
            'sidecar_subtitles': matching_subs,
            'recommended_output': f"encoded/{v.stem}.m2ts",
        }
        items.append(item)
    return {'project_dir':str(project), 'videos':items, 'subtitle_files':[p.name for p in subs]}


def ffmpeg_cmd(project: Path, item: dict, output_root: Path, seconds: int|None=None, burn_subtitle: str|None=None, progress_file: Path|None=None, encoder: str='cpu', resolution: str='1920x1080', cq: int=18, crf: int=18, audio_bitrate: str='640k', nvenc_preset: str='p5', cpu_preset: str='slow', video_bitrate: str|None=None, maxrate: str='40000k', bufsize: str='30000k'):
    src=project/item['file']
    out=output_root/item['recommended_output']
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        width, height = [int(x) for x in resolution.lower().split('x', 1)]
    except Exception:
        width, height = 1920, 1080
    vf=f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    if burn_subtitle:
        # Escape for ffmpeg subtitles filter. Keep simple for local paths.
        sub=str(project/burn_subtitle).replace("'", "\\'")
        vf += f",subtitles='{sub}'"
    cmd=['ffmpeg','-hide_banner','-y']
    if progress_file:
        progress_file.parent.mkdir(parents=True, exist_ok=True)
        cmd += ['-progress', str(progress_file), '-nostats']
    if seconds:
        cmd += ['-t', str(seconds)]
    cmd += ['-i', str(src), '-map','0:v:0','-map','0:a:0', '-vf', vf, '-r','24000/1001']
    if encoder == 'nvenc':
        cmd += [
            '-c:v','h264_nvenc', '-preset',str(nvenc_preset), '-tune','hq', '-rc','vbr',
            '-cq',str(cq), '-b:v',str(video_bitrate or '0'), '-maxrate',str(maxrate), '-bufsize',str(bufsize),
            '-profile:v','high', '-level:v','4.1', '-pix_fmt','yuv420p',
            '-g','24', '-bf','3', '-spatial_aq','1', '-temporal_aq','1',
        ]
    else:
        cmd += [
            '-c:v','libx264','-preset',str(cpu_preset),'-crf',str(crf),'-profile:v','high','-level:v','4.1',
            '-pix_fmt','yuv420p','-b:v',str(video_bitrate or '0'),'-maxrate',str(maxrate),'-bufsize',str(bufsize),'-x264-params',f'bluray-compat=1:vbv-maxrate={str(maxrate).rstrip("k")}:vbv-bufsize={str(bufsize).rstrip("k")}:keyint=24:min-keyint=1:slices=4',
        ]
    cmd += ['-c:a','ac3','-b:a',str(audio_bitrate),'-ar','48000', '-mpegts_m2ts_mode','1', str(out)]
    return cmd


def nvidia_status():
    try:
        smi=subprocess.run(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        enc=subprocess.run(['ffmpeg','-hide_banner','-encoders'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=10)
        return {
            'nvidia_smi': smi.stdout.strip() if smi.returncode == 0 else None,
            'h264_nvenc': 'h264_nvenc' in enc.stdout,
            'hevc_nvenc': 'hevc_nvenc' in enc.stdout,
            'available': smi.returncode == 0 and 'h264_nvenc' in enc.stdout,
        }
    except Exception as e:
        return {'available': False, 'error': str(e)}


def write_plan(project: Path, manifest: dict, output_root: Path):
    lines=['# FFmpeg Blu-ray media preparation plan', '', 'This prepares Blu-ray-friendly 1920x1080 H.264 + AC-3 `.m2ts` files.', '', '```bash']
    for item in manifest['videos']:
        cmd=ffmpeg_cmd(project, item, output_root, encoder='cpu')
        lines.append(' '.join(shlex.quote(x) for x in cmd))
    lines += ['```','', 'Subtitle note: Blu-ray selectable subtitles normally need PGS/SUP authoring. This workflow keeps `.srt` files mapped in the manifest for the next mux/authoring layer. For maximum compatibility today, burn subtitles into video when needed.']
    (output_root/'ffmpeg-plan.md').write_text('\n'.join(lines)+'\n')


def main():
    ap=argparse.ArgumentParser(description='Analyze and prepare media for the PPTX Blu-ray workflow.')
    ap.add_argument('project_dir')
    ap.add_argument('--output-root', default=None)
    ap.add_argument('--write-manifest', action='store_true')
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--encode', action='store_true')
    ap.add_argument('--smoke-seconds', type=int, default=None, help='encode only first N seconds')
    ap.add_argument('--only', default=None, help='only encode a video filename substring, e.g. "Video 1"')
    ap.add_argument('--burn-first-subtitle', action='store_true', help='burn first matching sidecar .srt into each encoded video')
    ap.add_argument('--encoder', choices=['auto','cpu','nvenc'], default='auto', help='video encoder backend; auto uses NVIDIA NVENC when available')
    ap.add_argument('--resolution', default='1920x1080', help='output frame size, e.g. 1920x1080 or 1280x720')
    ap.add_argument('--cq', type=int, default=18, help='NVENC constant-quality value; lower is higher quality')
    ap.add_argument('--crf', type=int, default=18, help='x264 CRF value; lower is higher quality')
    ap.add_argument('--audio-bitrate', default='640k', help='AC-3 audio bitrate')
    ap.add_argument('--nvenc-preset', default='p5', help='NVENC preset, e.g. p4/p5/p6/p7')
    ap.add_argument('--cpu-preset', default='slow', help='x264 preset, e.g. medium/slow/veryslow')
    ap.add_argument('--disc-preset', choices=['quality','bd25'], default='quality', help='quality keeps CRF/CQ behavior; bd25 targets single-layer BD-25 size')
    ap.add_argument('--video-bitrate', default=None, help='average video bitrate, e.g. 6200k; overrides disc preset')
    ap.add_argument('--maxrate', default='40000k', help='video VBV maxrate')
    ap.add_argument('--bufsize', default='30000k', help='video VBV buffer size')
    ap.add_argument('--gpu-status', action='store_true', help='print NVIDIA/NVENC detection and exit')
    args=ap.parse_args()
    if args.gpu_status:
        print(json.dumps(nvidia_status(), indent=2))
        return
    project=Path(args.project_dir).resolve()
    output_root=Path(args.output_root).resolve() if args.output_root else project/'build'/'bluray-media'
    output_root.mkdir(parents=True, exist_ok=True)
    manifest=discover(project)
    if args.write_manifest or args.plan or args.encode:
        (output_root/'media-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    if args.plan:
        write_plan(project, manifest, output_root)
    if args.encode:
        for item in manifest['videos']:
            if args.only and args.only.lower() not in item['file'].lower():
                continue
            burn=None
            if args.burn_first_subtitle and item['sidecar_subtitles']:
                burn=item['sidecar_subtitles'][0]['file']
            logs_dir=output_root/'logs'
            logs_dir.mkdir(parents=True, exist_ok=True)
            safe=item['file'].replace('/', '_')
            progress_file=logs_dir/(safe + '.progress')
            log_file=logs_dir/(safe + '.ffmpeg.log')
            state_file=logs_dir/(safe + '.state.json')
            selected_encoder = 'nvenc' if args.encoder == 'nvenc' or (args.encoder == 'auto' and nvidia_status().get('available')) else 'cpu'
            video_bitrate = args.video_bitrate
            audio_bitrate = args.audio_bitrate
            maxrate = args.maxrate
            bufsize = args.bufsize
            if args.disc_preset == 'bd25' and not video_bitrate:
                # Project is ~7.87h. 6200k video + 448k AC3 leaves room for menu/filesystem overhead on BD-25.
                video_bitrate = '6200k'
                audio_bitrate = '448k'
                maxrate = '12000k'
                bufsize = '15000k'
            state={
                'file': item['file'], 'started_at': time.time(), 'status': 'running', 'encoder': selected_encoder, 'pid': None,
                'duration_seconds': item.get('duration_seconds'),
                'output': str(output_root/item['recommended_output']),
                'progress_file': str(progress_file), 'log_file': str(log_file),
                'smoke_seconds': args.smoke_seconds,
                'options': {
                    'resolution': args.resolution, 'cq': args.cq, 'crf': args.crf,
                    'audio_bitrate': audio_bitrate, 'nvenc_preset': args.nvenc_preset,
                    'disc_preset': args.disc_preset, 'video_bitrate': video_bitrate,
                    'maxrate': maxrate, 'bufsize': bufsize,
                    'cpu_preset': args.cpu_preset,
                },
            }
            state_file.write_text(json.dumps(state, indent=2)+'\n')
            cmd=ffmpeg_cmd(project, item, output_root, args.smoke_seconds, burn, progress_file, selected_encoder, args.resolution, args.cq, args.crf, audio_bitrate, args.nvenc_preset, args.cpu_preset, video_bitrate, maxrate, bufsize)
            print('+', ' '.join(shlex.quote(x) for x in cmd), flush=True)
            try:
                with log_file.open('ab') as log:
                    proc=subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
                    state['pid']=proc.pid
                    state_file.write_text(json.dumps(state, indent=2)+'\n')
                    returncode=proc.wait()
                state['finished_at']=time.time()
                state['returncode']=returncode
                state['status']='done' if returncode == 0 else 'failed'
                state_file.write_text(json.dumps(state, indent=2)+'\n')
                if returncode != 0:
                    raise subprocess.CalledProcessError(returncode, cmd)
            finally:
                # ffmpeg writes progress=end on success; leave files behind for monitor/history.
                pass
    print(json.dumps(manifest, indent=2))

if __name__=='__main__':
    main()
