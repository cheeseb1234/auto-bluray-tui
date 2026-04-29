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


def export_slide_pngs(pptx: Path, out_assets: Path, target=(1920,1080)):
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


def draw_overlays(model, assets: Path, target=(1920,1080)):
    src_w, src_h = model['source_size_emu']
    sx, sy = target[0]/src_w, target[1]/src_h
    for slide in model['slides']:
        bg = Image.open(assets / f"{slide['id']}_bg.png").convert('RGBA')
        for btn in slide['buttons']:
            r=btn['rect_emu']
            x,y,w,h = round(r['x']*sx), round(r['y']*sy), round(r['w']*sx), round(r['h']*sy)
            btn['rect_px']={'x':x,'y':y,'w':w,'h':h}
            for state, outline in [('selected',(255,255,255,245)),('activated',(64,255,170,255))]:
                pad=8
                # Build the state image as an opaque crop from the rendered slide,
                # then draw only a border.  Some BD-J/libbluray paths don't handle
                # alpha-only overlay PNGs reliably; opaque crops preserve the exact
                # PowerPoint button text/art instead of covering it.
                crop_box=(max(0,x-pad), max(0,y-pad), min(target[0],x+w+pad), min(target[1],y+h+pad))
                im=Image.new('RGBA',(w+pad*2,h+pad*2),(0,0,0,255))
                crop=bg.crop(crop_box)
                im.paste(crop,(crop_box[0]-(x-pad), crop_box[1]-(y-pad)))
                d=ImageDraw.Draw(im)
                d.rounded_rectangle((2,2,w+pad*2-2,h+pad*2-2), radius=22, outline=outline, width=5)
                im.save(assets/f"{slide['id']}_{btn['id']}_{state}.png")


def button_grid(buttons):
    """Return GRIN visual-rc rows that follow the button positions on the slide."""
    rows=[]
    for btn in sorted(buttons, key=lambda b:(b['rect_px']['y'] + b['rect_px']['h']/2, b['rect_px']['x'])):
        cy=btn['rect_px']['y'] + btn['rect_px']['h']/2
        placed=False
        for row in rows:
            row_cy=sum(b['rect_px']['y'] + b['rect_px']['h']/2 for b in row)/len(row)
            row_h=max(b['rect_px']['h'] for b in row)
            if abs(cy-row_cy) <= max(40, row_h*0.45):
                row.append(btn); placed=True; break
        if not placed:
            rows.append([btn])
    return [sorted(row, key=lambda b:b['rect_px']['x']) for row in rows]


def visual_rc_grid(buttons):
    """Return a rectangular GRIN visual-rc grid.

    GRIN requires every grid row to have the same number of cells. PowerPoint
    menus often have an uneven layout (for example a single "Main Menu" button
    above two video buttons), so pad missing cells with coordinate placeholders.
    """
    rows = button_grid(buttons)
    if not rows:
        return []
    width = max(len(row) for row in rows)
    if width <= 1:
        return [[row[0]['id']] for row in rows]

    widest = max(rows, key=len)
    centers = [b['rect_px']['x'] + b['rect_px']['w'] / 2 for b in widest]
    grid=[]
    for row_index, row in enumerate(rows):
        cells=[None] * width
        used=set()
        for btn in row:
            cx=btn['rect_px']['x'] + btn['rect_px']['w'] / 2
            col=min((i for i in range(width) if i not in used), key=lambda i: abs(cx - centers[i]))
            cells[col]=btn['id']
            used.add(col)
        actual_cols=[i for i, cell in enumerate(cells) if cell is not None]
        for col in range(width):
            if cells[col] is None:
                target_col=min(actual_cols, key=lambda i: abs(i - col))
                cells[col]=f'( {target_col} {row_index} )'
        grid.append(cells)
    return grid


def generate_show(model, out: Path):
    lines=['# Generated from PowerPoint by tools/pptx_menu_converter.py','show','']
    lines += [
        'java_generated_class PptxMenuCommands [[',
        '    import com.hdcookbook.grin.Show;',
        '    import com.hdcookbook.grin.util.Debug;',
        '    import javax.media.Control;',
        '    import javax.media.Manager;',
        '    import javax.media.Player;',
        '    import org.bluray.media.PlayListChangeControl;',
        '    import org.bluray.net.BDLocator;',
        '    import org.davic.media.MediaLocator;',
        '    public class PptxMenuCommands extends com.hdcookbook.grin.GrinXHelper {',
        '        private static Player player;',
        '        private static PlayListChangeControl playlistControl;',
        '        public PptxMenuCommands(Show show) { super(show); }',
        '        public static synchronized void stopVideo() {',
        '            Debug.println("PPTX_MENU_STOP");',
        '            try {',
        '                if (player != null) { player.stop(); }',
        '            } catch (Throwable t) {',
        '                Debug.println("PPTX_MENU_STOP_FAILED");',
        '                if (Debug.LEVEL > 0) { Debug.printStackTrace(t); }',
        '            }',
        '        }',
        '        public synchronized void playVideo(String videoFile, String playlistId) {',
        '            Debug.println("PPTX_MENU_PLAY video=" + videoFile + " playlist=" + playlistId);',
        '            try {',
        '                GrinDriverXlet.hideMenuGraphics();',
        '                BDLocator loc = new BDLocator("bd://1.PLAYLIST:" + playlistId);',
        '                if (player == null) {',
        '                    player = Manager.createPlayer(new MediaLocator(loc));',
        '                    player.prefetch();',
        '                    Control[] controls = player.getControls();',
        '                    for (int i = 0; i < controls.length; i++) {',
        '                        if (controls[i] instanceof PlayListChangeControl) {',
        '                            playlistControl = (PlayListChangeControl) controls[i];',
        '                        }',
        '                    }',
        '                } else if (playlistControl != null) {',
        '                    player.stop();',
        '                    playlistControl.selectPlayList(loc);',
        '                } else {',
        '                    player.stop();',
        '                    player = Manager.createPlayer(new MediaLocator(loc));',
        '                    player.prefetch();',
        '                }',
        '                player.start();',
        '            } catch (Throwable t) {',
        '                Debug.println("PPTX_MENU_PLAY_FAILED video=" + videoFile + " playlist=" + playlistId);',
        '                if (Debug.LEVEL > 0) { Debug.printStackTrace(t); }',
        '            }',
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
    lines += [
        '# Empty segment used before video playback so GRIN has one frame to',
        '# erase any selected/activated button images from the graphics plane.',
        'segment S:VideoPlayback',
        '    active {',
        '    } setup {',
        '    }',
        ';',
        ''
    ]
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
        grid_rows=' '.join('{ ' + ' '.join(row) + ' }' for row in visual_rc_grid(buttons))
        lines += [f'rc_handler visual R:{sid}',f'    grid {{ {grid_rows} }}',f'    assembly F:{sid}.Buttons','        start_selected true','    select {']
        for btn in buttons:
            lines.append(f"        {btn['id']} {btn['id']}_selected")
        lines += ['    }','    activate {']
        for btn in buttons:
            bid=btn['id']; act=btn['action']
            if act['kind']=='slide':
                lines.append(f"        {bid} {bid}_activated {{ activate_segment S:{act['target']} ; }}")
            else:
                video=act['target'].replace('\\', '\\\\').replace('"', '\\"')
                playlist=act.get('playlist_id', '00000')
                lines.append(f"        {bid} {bid}_activated {{ activate_segment S:VideoPlayback ; sync_display ; java_command [[ playVideo(\"{video}\", \"{playlist}\"); ]] }}")
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
GRIN_COMPILER_OPTIONS=-avoid_optimization
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

These preview as button activation feedback and call a generated `playVideo(videoFile, playlistId)` hook that starts the matching Blu-ray playlist.
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
