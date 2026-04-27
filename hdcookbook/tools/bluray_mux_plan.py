#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, shutil, subprocess
from pathlib import Path


def which(name):
    return shutil.which(name)


def ffprobe_duration(path: Path):
    try:
        r=subprocess.run(['ffprobe','-hide_banner','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return float(r.stdout.strip())
    except Exception:
        return None


def main():
    ap=argparse.ArgumentParser(description='Create Blu-ray mux/ISO authoring plan from PPTX video actions.')
    ap.add_argument('project_dir')
    ap.add_argument('--menu-dir', default=None)
    args=ap.parse_args()

    project=Path(args.project_dir).resolve()
    root=Path(__file__).resolve().parents[1]
    menu_dir=Path(args.menu_dir).resolve() if args.menu_dir else root/'xlets/grin_samples/Scripts/PptxMenu'
    actions_path=menu_dir/'video-actions.json'
    if not actions_path.exists():
        raise SystemExit(f'Missing {actions_path}; run ./scripts/convert-pptx-menu.sh first')
    actions=json.loads(actions_path.read_text())

    out=project/'build/bluray-authoring'
    meta_dir=out/'tsmuxer-meta'
    meta_dir.mkdir(parents=True, exist_ok=True)

    source_durations={}
    manifest_path=project/'build/bluray-media/media-manifest.json'
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        source_durations={v['file']: float(v.get('duration_seconds') or 0) for v in manifest.get('videos', [])}

    rows=[]
    for action in actions:
        encoded=project/action['encoded_m2ts']
        exists=encoded.exists()
        encoded_duration=ffprobe_duration(encoded) if exists else None
        source_duration=source_durations.get(action['video_file'])
        full_length = bool(encoded_duration and source_duration and encoded_duration >= max(1, source_duration - 2))
        valid=bool(encoded_duration)
        row={**action, 'encoded_abs': str(encoded), 'encoded_exists': exists, 'ffprobe_ok': valid,
             'encoded_duration_seconds': encoded_duration, 'source_duration_seconds': source_duration, 'full_length_encode': full_length,
             'clip_id': action['playlist_id'], 'stream_file': f"{action['playlist_id']}.m2ts"}
        rows.append(row)
        meta=(meta_dir/f"{action['playlist_id']}_{Path(action['video_file']).stem}.meta")
        meta.write_text(f'''# tsMuxer template for {action['button']} -> {action['video_file']}
# Input should already be Blu-ray-friendly H.264 + AC-3 from prepare-bluray-media.sh
MUXOPT --blu-ray --vbr --auto-chapters=5 --new-audio-pes
V_MPEG4/ISO/AVC, "{encoded}", fps=23.976, insertSEI, contSPS
A_AC3, "{encoded}", lang=eng
''')

    tool_status={
        'ffmpeg': which('ffmpeg'),
        'ffprobe': which('ffprobe'),
        'tsMuxer': which('tsMuxer') or which('tsmuxer'),
        'xorriso': which('xorriso'),
        'mkisofs': which('mkisofs') or which('genisoimage'),
        'bdsup2sub': which('bdsup2sub'),
    }
    plan={'project_dir':str(project), 'menu_dir':str(menu_dir), 'tool_status':tool_status, 'video_playlist_map':rows}
    (out/'playlist-map.json').write_text(json.dumps(plan, indent=2)+'\n')

    lines=['# Blu-ray mux/ISO authoring plan', '', '## Tool status', '']
    for k,v in tool_status.items():
        lines.append(f'- {k}: `{v or "MISSING"}`')
    lines += ['', '## Video button → playlist map', '']
    for r in rows:
        if r['full_length_encode']:
            status='ready/full-length'
        elif r['ffprobe_ok']:
            status=f"partial/smoke encode ({r['encoded_duration_seconds']:.1f}s of {r.get('source_duration_seconds') or 0:.1f}s)"
        else:
            status='missing/not encoded yet'
        lines.append(f"- {r['button']} → `{r['video_file']}` → playlist `{r['playlist_id']}` / title `{r['title_number']}` → `{r['encoded_abs']}` ({status})")
    lines += ['', '## Next commands', '']
    lines.append('1. Encode all linked videos:')
    lines.append('')
    lines.append('```bash')
    lines.append(f'./scripts/prepare-bluray-media.sh {str(project)!r}')
    lines.append('```')
    lines.append('')
    lines.append('2. Install/add muxing tools before final authoring: `tsMuxer` and `xorriso` or `mkisofs`.')
    lines.append('')
    lines.append('3. Use the generated tsMuxer metadata templates:')
    lines.append('')
    lines.append('```text')
    lines.append(str(meta_dir))
    lines.append('```')
    lines.append('')
    lines.append('4. Replace the generated `PptxMenuCommands.playVideo(videoFile, playlistId)` hook with BD-J title/playlist navigation once the final playlist IDs exist in the authored BDMV tree.')
    lines.append('')
    lines.append('## Important caveat')
    lines.append('')
    lines.append('The tsMuxer meta files are templates. They are intentionally generated now so playlist IDs and menu button IDs are stable, but they should be validated with tsMuxer installed before treating the final disc as complete.')
    (out/'mux-plan.md').write_text('\n'.join(lines)+'\n')

    print(json.dumps(plan, indent=2))

if __name__ == '__main__':
    main()
