#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, shlex, subprocess, sys
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


def ffmpeg_cmd(project: Path, item: dict, output_root: Path, seconds: int|None=None, burn_subtitle: str|None=None):
    src=project/item['file']
    out=output_root/item['recommended_output']
    out.parent.mkdir(parents=True, exist_ok=True)
    vf="scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1"
    if burn_subtitle:
        # Escape for ffmpeg subtitles filter. Keep simple for local paths.
        sub=str(project/burn_subtitle).replace("'", "\\'")
        vf += f",subtitles='{sub}'"
    cmd=['ffmpeg','-hide_banner','-y']
    if seconds:
        cmd += ['-t', str(seconds)]
    cmd += ['-i', str(src), '-map','0:v:0','-map','0:a:0',
            '-vf', vf,
            '-r','24000/1001',
            '-c:v','libx264','-preset','slow','-crf','18','-profile:v','high','-level:v','4.1',
            '-pix_fmt','yuv420p','-x264-params','bluray-compat=1:vbv-maxrate=40000:vbv-bufsize=30000:keyint=24:min-keyint=1:slices=4',
            '-c:a','ac3','-b:a','640k','-ar','48000',
            '-mpegts_m2ts_mode','1', str(out)]
    return cmd


def write_plan(project: Path, manifest: dict, output_root: Path):
    lines=['# FFmpeg Blu-ray media preparation plan', '', 'This prepares Blu-ray-friendly 1920x1080 H.264 + AC-3 `.m2ts` files.', '', '```bash']
    for item in manifest['videos']:
        cmd=ffmpeg_cmd(project, item, output_root)
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
    args=ap.parse_args()
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
            cmd=ffmpeg_cmd(project, item, output_root, args.smoke_seconds, burn)
            print('+', ' '.join(shlex.quote(x) for x in cmd), flush=True)
            subprocess.run(cmd, check=True)
    print(json.dumps(manifest, indent=2))

if __name__=='__main__':
    main()
