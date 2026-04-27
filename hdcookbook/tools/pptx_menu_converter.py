#!/usr/bin/env python3
from __future__ import annotations

import json, re, shutil, subprocess, sys, tempfile, zipfile, xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

NS = {
    'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}
RID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
RELNS = '{http://schemas.openxmlformats.org/package/2006/relationships}'


def ident(s: str) -> str:
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_')
    if not s or s[0].isdigit():
        s = 'x_' + s
    return s


def read_rels(z, path):
    if path not in z.namelist(): return {}
    root = ET.fromstring(z.read(path))
    return {r.attrib['Id']: r.attrib for r in root}


def extract_slide_model(pptx: Path, project_dir: Path):
    videos = {p.stem.lower(): p.name for p in project_dir.iterdir() if p.suffix.lower() in ('.mp4','.mkv','.m2ts','.mov')}
    subtitles = [p.name for p in project_dir.iterdir() if p.suffix.lower() in ('.srt','.sup','.ass','.ssa')]
    with zipfile.ZipFile(pptx) as z:
        pres = ET.fromstring(z.read('ppt/presentation.xml'))
        size = pres.find('p:sldSz', NS).attrib
        src_w, src_h = int(size['cx']), int(size['cy'])
        slide_names = sorted([n for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', n)], key=lambda n:int(re.search(r'(\d+)', n).group(1)))
        slides=[]
        for idx, slide_path in enumerate(slide_names, 1):
            root=ET.fromstring(z.read(slide_path))
            rels=read_rels(z, f'ppt/slides/_rels/slide{idx}.xml.rels')
            buttons=[]
            title=None
            texts=[]
            for sp in root.findall('.//p:sp', NS):
                parts=[t.text or '' for t in sp.findall('.//a:t', NS)]
                text=' '.join(' '.join(parts).split()).strip()
                if not text: continue
                texts.append(text)
                xfrm=sp.find('.//a:xfrm', NS)
                if xfrm is None: continue
                off=xfrm.find('a:off', NS); ext=xfrm.find('a:ext', NS)
                if off is None or ext is None: continue
                rect={k:int(v) for k,v in {
                    'x':off.attrib['x'], 'y':off.attrib['y'], 'w':ext.attrib['cx'], 'h':ext.attrib['cy']}.items()}
                link=None
                for h in sp.findall('.//a:hlinkClick', NS):
                    action=h.attrib.get('action','')
                    rid=h.attrib.get(RID,'')
                    if 'firstslide' in action:
                        link={'kind':'slide','target':'slide1'}
                    elif rid and rid in rels and rels[rid]['Type'].endswith('/slide'):
                        m=re.search(r'slide(\d+)\.xml', rels[rid]['Target'])
                        if m: link={'kind':'slide','target':f'slide{m.group(1)}'}
                video_name = videos.get(text.lower())
                if link or video_name:
                    buttons.append({
                        'id': ident(text), 'label': text, 'rect_emu': rect,
                        'action': link or {'kind':'video','target': video_name}
                    })
                if title is None and not link and not video_name:
                    title=text
            slides.append({'id':f'slide{idx}', 'title':title or f'Slide {idx}', 'texts':texts, 'buttons':buttons})
    return {'source': str(pptx), 'slides': slides, 'source_size_emu':[src_w,src_h], 'videos': videos, 'subtitles': subtitles}


def assign_video_actions(model):
    video_buttons=[]
    seen={}
    next_playlist=1
    for slide in model['slides']:
        for btn in slide['buttons']:
            act=btn['action']
            if act['kind'] != 'video':
                continue
            target=act['target']
            if target not in seen:
                seen[target]={
                    'video_file': target,
                    'playlist_id': f'{next_playlist:05d}',
                    'title_number': next_playlist,
                    'encoded_m2ts': f'build/bluray-media/encoded/{Path(target).stem}.m2ts'
                }
                next_playlist += 1
            act.update(seen[target])
            video_buttons.append({
                'slide': slide['id'],
                'button': btn['label'],
                **seen[target]
            })
    model['video_actions']=video_buttons


def export_slide_pngs(pptx: Path, out_assets: Path, target=(1280,720)):
    out_assets.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        subprocess.run(['libreoffice','--headless','--convert-to','pdf','--outdir',str(td),str(pptx)], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        pdf=td/(pptx.stem+'.pdf')
        subprocess.run(['pdftoppm','-png','-r','96',str(pdf),str(td/'slide')], check=True)
        pngs=sorted(td.glob('slide-*.png'))
        for i,p in enumerate(pngs,1):
            im=Image.open(p).convert('RGB').resize(target, Image.LANCZOS)
            im.save(out_assets/f'slide{i}_bg.png')


def draw_overlays(model, assets: Path, target=(1280,720)):
    src_w, src_h = model['source_size_emu']
    sx, sy = target[0]/src_w, target[1]/src_h
    try:
        font=ImageFont.truetype('/usr/share/fonts/TTF/DejaVuSans-Bold.ttf', 26)
    except Exception:
        font=ImageFont.load_default()
    for slide in model['slides']:
        for btn in slide['buttons']:
            r=btn['rect_emu']
            x,y,w,h = round(r['x']*sx), round(r['y']*sy), round(r['w']*sx), round(r['h']*sy)
            btn['rect_px']={'x':x,'y':y,'w':w,'h':h}
            for state, fill, outline in [('selected',(64,170,255,70),(255,255,255,230)),('activated',(64,255,170,130),(255,255,255,255))]:
                pad=8
                im=Image.new('RGBA',(w+pad*2,h+pad*2),(0,0,0,0))
                d=ImageDraw.Draw(im)
                d.rounded_rectangle((2,2,w+pad*2-2,h+pad*2-2), radius=22, fill=fill, outline=outline, width=4)
                # Keep the underlying PPT label visible; just add a subtle play glyph for video buttons.
                if btn['action']['kind']=='video':
                    d.polygon([(pad+18,pad+18),(pad+18,pad+h-18),(pad+48,pad+h//2)], fill=(255,255,255,230))
                im.save(assets/f"{slide['id']}_{btn['id']}_{state}.png")


def generate_show(model, out: Path):
    lines=['# Generated from PowerPoint by tools/pptx_menu_converter.py','show','']
    lines += [
        'java_generated_class PptxMenuCommands [[',
        '    import com.hdcookbook.grin.Show;',
        '    import com.hdcookbook.grin.util.Debug;',
        '    public class PptxMenuCommands extends com.hdcookbook.grin.GrinXHelper {',
        '        public PptxMenuCommands(Show show) { super(show); }',
        '        public void playVideo(String videoFile, String playlistId) {',
        '            Debug.println("PPTX_MENU_PLAY video=" + videoFile + " playlist=" + playlistId);',
        '        }',
        '        JAVA_COMMAND_BODY',
        '    }',
        ']]',
        ''
    ]
    first=model['slides'][0]['id']
    lines += [
        'segment S:Initialize',
        '    setup {', f'        F:{first}.BG', '    } setup_done {', f'        activate_segment S:{first} ;', '    }',';',''
    ]
    for slide in model['slides']:
        sid=slide['id']
        lines += [f'segment S:{sid}','    active {',f'        F:{sid}.BG',f'        F:{sid}.Buttons','    } setup {',f'        F:{sid}.BG',f'        F:{sid}.Buttons','    } rc_handlers {',f'        R:{sid}','    }',';','']
    for slide in model['slides']:
        sid=slide['id']
        lines.append(f'feature fixed_image F:{sid}.BG 0 0 "assets/{sid}_bg.png" ;')
        for btn in slide['buttons']:
            x=btn['rect_px']['x']-8; y=btn['rect_px']['y']-8
            bid=btn['id']
            lines.append(f'feature fixed_image F:{sid}.{bid}.Selected {x} {y} "assets/{sid}_{bid}_selected.png" ;')
            lines.append(f'feature fixed_image F:{sid}.{bid}.Activated {x} {y} "assets/{sid}_{bid}_activated.png" ;')
        lines.append('')
    for slide in model['slides']:
        sid=slide['id']; buttons=slide['buttons']
        lines.append(f'feature assembly F:{sid}.Buttons {{')
        for btn in buttons:
            bid=btn['id']
            lines.append(f'    {bid}_selected F:{sid}.{bid}.Selected')
            lines.append(f'    {bid}_activated F:{sid}.{bid}.Activated')
        lines += ['} ;','']
        if not buttons: continue
        grid=' '.join(btn['id'] for btn in buttons)
        lines += [f'rc_handler visual R:{sid}',f'    grid {{ {{ {grid} }} }}',f'    assembly F:{sid}.Buttons','        start_selected true','    select {']
        for btn in buttons:
            lines.append(f"        {btn['id']} {btn['id']}_selected")
        lines += ['    }','    activate {']
        for btn in buttons:
            bid=btn['id']; act=btn['action']
            if act['kind']=='slide':
                lines.append(f"        {bid} {bid}_activated {{ activate_segment S:{act['target']} ; }}")
            else:
                video=act['target'].replace('\\', '\\\\').replace('"', '\"')
                playlist=act.get('playlist_id', '00000')
                lines.append(f"        {bid} {bid}_activated {{ java_command [[ playVideo(\"{video}\", \"{playlist}\"); ]] activate_segment S:{sid} ; }}")
        lines += ['    }','    mouse {']
        for btn in buttons:
            r=btn['rect_px']; lines.append(f"        {btn['id']} ( {r['x']} {r['y']} {r['x']+r['w']} {r['y']+r['h']} )")
        lines += ['    }',';','']
    lines.append('end_show')
    (out/'pptx-menu.txt').write_text('\n'.join(lines)+'\n')


def write_build_files(out: Path, model):
    (out/'build.properties').write_text('''build.dir=build
xlet.jar=${build.dir}/00000.jar
script.name=pptx-menu
generated.class=PptxMenuCommands.java
top.dir=../../../..

bin.dir=${top.dir}/bin
bdjo-desc-file=00000.xml
bdjoconverter.jar=${bin.dir}/bdjo.jar
grinviewer.jar=${bin.dir}/grinviewer.jar
converter.jar=${bin.dir}/grincompiler.jar
grin.library.src.dir=${top.dir}/AuthoringTools/grin/library/src
''')
    (out/'build.xml').write_text('''<?xml version="1.0" encoding="UTF-8"?>
<project name="PptxMenu sample" default="default" basedir=".">
    <property file="build.properties"/>
    <import file="../../GrinDriverXlet/build.xml"/>
    <import file="../../GrinDriverXlet/generate-bdjo-desc.xml"/>
    <target name="default" depends="copy-xlet, all"/>
    <target name="preview" depends="run-grinview"/>
    <target name="autotest" depends="autotest-grinview"/>
</project>
''')
    (out/'README.md').write_text(f'''# PptxMenu — generated from menu.pptx

Generated from:

```text
{model['source']}
```

Edit the PowerPoint, then rerun:

```bash
./scripts/convert-pptx-menu.sh "/home/corey/.openclaw/Bluray project"
```

Preview:

```bash
cd xlets/grin_samples/Scripts/PptxMenu
ant preview
```

## Detected video actions

{json.dumps([{'slide':s['id'],'button':b['label'],'action':b['action']} for s in model['slides'] for b in s['buttons'] if b['action']['kind']=='video'], indent=2)}

These preview as button activation feedback and emit `PPTX_MENU_PLAY` lines through a generated `playVideo(videoFile, playlistId)` hook. The next step is replacing that hook with real BD-J playlist/title playback.
''')


def main():
    if len(sys.argv)!=3:
        print('usage: pptx_menu_converter.py PROJECT_DIR OUTPUT_DIR', file=sys.stderr); sys.exit(2)
    project_dir=Path(sys.argv[1]).resolve(); out=Path(sys.argv[2]).resolve()
    pptx=project_dir/'menu.pptx'
    if not pptx.exists(): raise SystemExit(f'No menu.pptx in {project_dir}')
    if out.exists(): shutil.rmtree(out)
    (out/'assets').mkdir(parents=True)
    model=extract_slide_model(pptx, project_dir)
    assign_video_actions(model)
    export_slide_pngs(pptx, out/'assets')
    draw_overlays(model, out/'assets')
    generate_show(model, out)
    write_build_files(out, model)
    (out/'menu-model.json').write_text(json.dumps(model, indent=2)+'\n')
    (out/'video-actions.json').write_text(json.dumps(model.get('video_actions', []), indent=2)+'\n')
    print(f'Generated {out}')
    print(f"Slides: {len(model['slides'])}; buttons: {sum(len(s['buttons']) for s in model['slides'])}")

if __name__=='__main__': main()
