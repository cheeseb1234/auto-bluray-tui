#!/usr/bin/env python3
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import webbrowser
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from button_action_parser import (
    VIDEO_EXTS,
    parse_button_action,
    parse_timestamp,
    split_display_action,
)
from PIL import Image, ImageDraw

try:
    from menu_backends import analyze_menu_compatibility, write_compatibility_report
except Exception:
    analyze_menu_compatibility = None
    write_compatibility_report = None

try:
    from html_menu_preview import make_preview as write_html_menu_preview
except Exception:
    write_html_menu_preview = None

NS = {
    'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
    'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}
RID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
RELNS = '{http://schemas.openxmlformats.org/package/2006/relationships}'
DEFAULT_MENU_TEMPLATE = Path('/mnt/llm/example/menu-template.pptx')


def ident(s: str) -> str:
    s = re.sub(r'[^A-Za-z0-9]+', '_', s).strip('_')
    if not s or s[0].isdigit():
        s = 'x_' + s
    return s


def read_rels(z, path):
    if path not in z.namelist(): return {}
    root = ET.fromstring(z.read(path))
    return {r.attrib['Id']: r.attrib for r in root}


def match_key(s: str) -> str:
    """Normalize labels/filenames enough for PPTX text to match media files."""
    return re.sub(r'[^a-z0-9]+', ' ', s.lower()).strip()


NOISE_WORDS = {
    '4k', 'uhd', '1080p', '720p', 'bluray', 'blu', 'ray', 'bd', 'remux',
    'x264', 'x265', 'h264', 'h265', 'hevc', 'aac', 'ac3', 'dts', 'truehd',
    'proper', 'repack', 'extended', 'theatrical', 'despecialized', 'edition',
}


def relaxed_key(s: str) -> str:
    """A looser key for safe auto-correction of common filename/label drift."""
    words = [w for w in match_key(s).split() if w not in NOISE_WORDS]
    return ' '.join(words)


def unique_id(base: str, used: set[str]) -> str:
    candidate = ident(base)
    if candidate not in used:
        used.add(candidate)
        return candidate
    i = 2
    while f'{candidate}_{i}' in used:
        i += 1
    candidate = f'{candidate}_{i}'
    used.add(candidate)
    return candidate


def project_videos(project_dir: Path) -> list[Path]:
    return sorted([p for p in project_dir.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS], key=lambda p: p.name.lower())


def find_project_pptx(project_dir: Path) -> Path | None:
    """Return the project's single PPTX menu, regardless of filename.

    If no PPTX exists, callers can generate one.  If multiple PPTX files exist,
    fail loudly rather than guessing which menu to author.
    """
    pptxs = sorted([p for p in project_dir.iterdir() if p.is_file() and p.suffix.lower() == '.pptx' and not p.name.startswith('~$')], key=lambda p: p.name.lower())
    if not pptxs:
        return None
    if len(pptxs) > 1:
        names = ', '.join(p.name for p in pptxs[:8])
        raise SystemExit(f'Multiple .pptx files found in {project_dir}; keep exactly one menu PPTX. Found: {names}')
    return pptxs[0]


def split_groups(items, size=3):
    return [items[i:i+size] for i in range(0, len(items), size)]


def ppt_shape(shape_id: int, label: str, x: int, y: int, w: int, h: int, rid: str | None = None, *, title=False) -> str:
    label_xml = xml_escape(label)
    link = f'<a:hlinkClick r:id="{rid}" action="ppaction://hlinksldjump"/>' if rid else ''
    fill = '<a:noFill/>' if title else '<a:solidFill><a:srgbClr val="729fcf"/></a:solidFill>'
    line = '<a:ln w="0"><a:noFill/></a:ln>' if title else '<a:ln w="0"><a:solidFill><a:srgbClr val="3465a4"/></a:solidFill></a:ln>'
    size = '2800' if title else '1800'
    return f'''<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="">{link}</p:cNvPr><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{fill}{line}</p:spPr><p:txBody><a:bodyPr lIns="90000" rIns="90000" tIns="45000" bIns="45000" anchor="ctr"><a:noAutofit/></a:bodyPr><a:p><a:pPr algn="ctr"/><a:r><a:rPr lang="en-US" sz="{size}"><a:solidFill><a:srgbClr val="000000"/></a:solidFill><a:latin typeface="Arial"/></a:rPr><a:t>{label_xml}</a:t></a:r></a:p></p:txBody></p:sp>'''


def ppt_slide_xml(title: str, buttons: list[dict], slide_w: int, slide_h: int) -> str:
    title_w = int(slide_w * 0.68); title_h = 520000
    title_x = (slide_w - title_w) // 2; title_y = 360000
    btn_w = int(slide_w * 0.27); btn_h = 685800
    start_y = int(slide_h * 0.34); gap_y = 230000
    cols = min(3, max(1, len([b for b in buttons if b.get('kind') != 'main'])) )
    shapes = [ppt_shape(10, title, title_x, title_y, title_w, title_h, title=True)]
    sid = 11
    normal = [b for b in buttons if b.get('kind') != 'main']
    for i, b in enumerate(normal):
        row, col = divmod(i, cols)
        total_w = cols * btn_w + (cols - 1) * 420000
        x = (slide_w - total_w) // 2 + col * (btn_w + 420000)
        y = start_y + row * (btn_h + gap_y)
        shapes.append(ppt_shape(sid, b['label'], x, y, btn_w, btn_h, b.get('rid'))); sid += 1
    for b in [b for b in buttons if b.get('kind') == 'main']:
        shapes.append(ppt_shape(sid, b['label'], (slide_w - btn_w)//2, int(slide_h * 0.80), btn_w, btn_h, b.get('rid'))); sid += 1
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>{''.join(shapes)}</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'''


def ppt_slide_rels(links: list[tuple[str, int]]) -> str:
    rels = ['<?xml version="1.0" encoding="UTF-8"?>', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for rid, target in links:
        rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slide{target}.xml"/>')
    rels.append('<Relationship Id="rIdLayout" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>')
    rels.append('</Relationships>')
    return ''.join(rels)


def generate_menu_pptx_from_template(project_dir: Path, pptx: Path, template: Path = DEFAULT_MENU_TEMPLATE):
    videos = project_videos(project_dir)
    if not videos:
        raise SystemExit(f'No videos found in {project_dir}; cannot generate a menu PPTX')
    if not template.exists():
        raise SystemExit(f'No project PPTX and template missing: {template}')
    groups = split_groups(videos, 3)
    slide_count = 1 + len(groups)
    with zipfile.ZipFile(template) as zin:
        pres = ET.fromstring(zin.read('ppt/presentation.xml'))
        size = pres.find('p:sldSz', NS).attrib
        slide_w, slide_h = int(size['cx']), int(size['cy'])
        tmp = pptx.with_suffix('.tmp.pptx')
        skip = {'ppt/presentation.xml', 'ppt/_rels/presentation.xml.rels', '[Content_Types].xml'}
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename in skip or re.match(r'ppt/slides/(?:_rels/)?slide\d+\.xml(?:\.rels)?$', item.filename):
                    continue
                zout.writestr(item, zin.read(item.filename))
            # Main slide: one button per generated movie page, labels list up to 3 video stems.
            main_buttons=[]; main_links=[]
            for i, group in enumerate(groups, 2):
                rid=f'rId{i}'
                main_links.append((rid, i))
                main_buttons.append({'label': ', '.join(p.stem for p in group), 'rid': rid})
            zout.writestr('ppt/slides/slide1.xml', ppt_slide_xml('Main Menu', main_buttons, slide_w, slide_h))
            zout.writestr('ppt/slides/_rels/slide1.xml.rels', ppt_slide_rels(main_links))
            for idx, group in enumerate(groups, 2):
                buttons=[{'label': p.stem} for p in group]
                buttons.append({'label': 'Main Menu', 'rid': 'rIdMain', 'kind': 'main'})
                zout.writestr(f'ppt/slides/slide{idx}.xml', ppt_slide_xml(f'Videos {idx-1}', buttons, slide_w, slide_h))
                zout.writestr(f'ppt/slides/_rels/slide{idx}.xml.rels', ppt_slide_rels([('rIdMain', 1)]))
            sld_ids = ''.join(f'<p:sldId id="{255+i}" r:id="rId{2+i}"/>' for i in range(1, slide_count+1))
            pres_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId2"/></p:sldMasterIdLst><p:sldIdLst>{sld_ids}</p:sldIdLst><p:sldSz cx="{slide_w}" cy="{slide_h}"/><p:notesSz cx="7772400" cy="10058400"/></p:presentation>'''
            zout.writestr('ppt/presentation.xml', pres_xml)
            pres_rels = ['<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>']
            for i in range(1, slide_count+1):
                pres_rels.append(f'<Relationship Id="rId{2+i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>')
            pres_rels.append('<Relationship Id="rId999" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/presProps" Target="presProps.xml"/></Relationships>')
            zout.writestr('ppt/_rels/presentation.xml.rels', ''.join(pres_rels))
            ct = zin.read('[Content_Types].xml').decode('utf-8')
            ct = re.sub(r'<Override PartName="/ppt/slides/slide\d+\.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide\+xml"/>', '', ct)
            inserts=''.join(f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(1, slide_count+1))
            ct = ct.replace('</Types>', inserts + '</Types>')
            zout.writestr('[Content_Types].xml', ct)
    tmp.replace(pptx)
    print(f'Generated template menu: {pptx} ({len(videos)} videos, {slide_count} slides)')


def find_video_match(label: str, videos: dict[str, str]):
    """Return (filename, note) for a PPTX label, with conservative autocorrection."""
    exact = videos.get(label.lower()) or videos.get(match_key(label))
    if exact:
        return exact, None

    relaxed = relaxed_key(label)
    relaxed_hits = sorted({name for key, name in videos.items() if relaxed and relaxed_key(key) == relaxed})
    if len(relaxed_hits) == 1:
        return relaxed_hits[0], f'relaxed label match: "{label}" -> "{relaxed_hits[0]}"'

    label_words = set(relaxed.split())
    subset_hits = sorted({name for key, name in videos.items() if label_words and label_words <= set(relaxed_key(key).split())})
    if len(subset_hits) == 1:
        return subset_hits[0], f'partial label match: "{label}" -> "{subset_hits[0]}"'

    keys = [k for k in videos if k]
    scored = []
    for key in keys:
        score = max(
            difflib.SequenceMatcher(None, match_key(label), key).ratio(),
            difflib.SequenceMatcher(None, relaxed, relaxed_key(key)).ratio() if relaxed else 0,
        )
        scored.append((score, key, videos[key]))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= 0.88 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08):
        return scored[0][2], f'fuzzy label match: "{label}" -> "{scored[0][2]}" ({scored[0][0]:.2f})'
    return None, None


def parse_timecode(value: str) -> int | None:
    """Compatibility wrapper; Grammar v1 parser uses parse_timestamp."""
    seconds, _ = parse_timestamp(value)
    return seconds


def split_button_action_text(raw_text: str) -> tuple[str, str, list[str]]:
    """Compatibility wrapper for older tests/callers."""
    return split_display_action(raw_text)


def parse_chapter_action(label: str, videos: dict[str, str]):
    """Compatibility wrapper for older tests/callers; prefer parse_button_action."""
    action, warnings = parse_button_action(label, videos)
    if action and action.get('kind') == 'video' and action.get('start_time_seconds') is not None:
        return action, warnings[0] if warnings else None
    return None, warnings[0] if warnings else None


def resolve_slide_action_targets(model: dict):
    slides = model.get('slides') or []
    lookup = {}
    for slide in slides:
        for value in (slide.get('id'), slide.get('title')):
            if value:
                lookup.setdefault(match_key(str(value)), slide['id'])
    for slide in slides:
        for btn in slide.get('buttons') or []:
            action = btn.get('action') or {}
            if action.get('kind') == 'slide' and action.get('target_label') and not action.get('target'):
                target = lookup.get(match_key(action['target_label']))
                if target:
                    action['target'] = target
                else:
                    warning = f'goto target "{action["target_label"]}" does not match any slide title/id'
                    btn.setdefault('parse_warnings', []).append(warning)
                    model.setdefault('match_warnings', []).append({'slide': slide.get('id'), 'label': btn.get('raw_text') or btn.get('label'), 'message': warning})


def looks_like_button_shape(sp, rect: dict | None) -> bool:
    """Heuristic: treat filled rectangular text shapes as clickable buttons.

    Some real-world PPTX menus use plain text on a rounded/rectangular filled
    shape without an explicit `goto:` grammar action. Those should still be kept
    as button candidates instead of being swallowed as slide titles.
    """
    if not rect:
        return False
    geom = sp.find('./p:spPr/a:prstGeom', NS)
    if geom is None or geom.attrib.get('prst') not in {'rect', 'roundRect'}:
        return False
    has_fill = sp.find('./p:spPr/a:solidFill', NS) is not None
    has_line = sp.find('./p:spPr/a:ln', NS) is not None
    if not (has_fill or has_line):
        return False
    return rect.get('w', 0) >= 300000 and rect.get('h', 0) >= 180000


def repair_conflicting_slide_links(model: dict) -> None:
    """Recover likely nav buttons when a PPTX slide link landed on the wrong shape.

    LibreOffice/PowerPoint round-trips occasionally preserve the visible button
    text boxes but attach the slide hyperlink to a neighboring video button. When
    we see exactly one unresolved button and at least one video button carrying a
    hidden slide link, prefer the unresolved button as the menu-navigation target
    and keep the video button as a video action.
    """
    for slide in model.get('slides') or []:
        buttons = slide.get('buttons') or []
        unresolved = [
            btn for btn in buttons
            if (btn.get('action') or {}).get('kind') in {'unresolved', 'invalid'}
        ]
        conflicted = [
            btn for btn in buttons
            if (btn.get('action') or {}).get('kind') == 'video'
            and (btn.get('link_action') or {}).get('kind') == 'slide'
        ]
        targets = sorted({(btn.get('link_action') or {}).get('target') for btn in conflicted if (btn.get('link_action') or {}).get('target')})
        if len(unresolved) != 1 or not conflicted or len(targets) != 1:
            continue
        target = targets[0]
        candidate = unresolved[0]
        original_target_label = (candidate.get('action') or {}).get('target_label') or candidate.get('label')
        stale_warning = f'video target not found: {original_target_label}'
        candidate['parse_warnings'] = [w for w in candidate.get('parse_warnings', []) if w != stale_warning]
        model['match_warnings'] = [
            item for item in (model.get('match_warnings') or [])
            if not (
                item.get('slide') == slide.get('id')
                and (item.get('label') == candidate.get('raw_text') or item.get('label') == candidate.get('label'))
                and item.get('message') == stale_warning
            )
        ]
        candidate['action'] = {
            'kind': 'slide',
            'target': target,
            'target_label': target,
            'type': 'go_to_menu',
            'inferred_from_conflicting_link': True,
        }
        candidate.setdefault('parse_warnings', []).append(
            f'inferred slide target "{target}" from neighboring conflicting hyperlink'
        )
        model.setdefault('match_warnings', []).append({
            'slide': slide.get('id'),
            'label': candidate.get('raw_text') or candidate.get('label'),
            'message': f'inferred slide target "{target}" from neighboring conflicting hyperlink',
        })


def is_loop_placeholder(label: str, video_name: str|None, link: dict|None, rect: dict|None, src_size: tuple[int, int]):
    """Detect PowerPoint shapes intended to become autoplay/looping slide video.

    A normal text shape matching a movie title remains a selectable button.  A
    shape matching a project video with a background/preview/loop/autoplay name,
    or a very large unlinked video-matching rectangle, is treated as a video
    placeholder: the rendered shape is cut out of the graphics layer and the
    matching clip is played behind it on a loop.
    """
    if not video_name or link:
        return False
    key = relaxed_key(label + ' ' + Path(video_name).stem)
    if any(word in key.split() for word in ('background', 'preview', 'loop', 'autoplay')):
        return True
    if rect:
        src_w, src_h = src_size
        area = rect.get('w', 0) * rect.get('h', 0)
        return area >= (src_w * src_h * 0.20)
    return False


def extract_slide_model(pptx: Path, project_dir: Path):
    videos = {}
    for p in project_dir.iterdir():
        if p.suffix.lower() in ('.mp4','.mkv','.m2ts','.mov'):
            videos[p.name.lower()] = p.name
            videos[p.stem.lower()] = p.name
            videos.setdefault(match_key(p.name), p.name)
            videos.setdefault(match_key(p.stem), p.name)
    subtitles = [p.name for p in project_dir.iterdir() if p.suffix.lower() in ('.srt','.sup','.ass','.ssa')]
    with zipfile.ZipFile(pptx) as z:
        pres = ET.fromstring(z.read('ppt/presentation.xml'))
        size = pres.find('p:sldSz', NS).attrib
        src_w, src_h = int(size['cx']), int(size['cy'])
        slide_names = sorted([n for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', n)], key=lambda n:int(re.search(r'(\d+)', n).group(1)))
        slides=[]
        match_warnings=[]
        for idx, slide_path in enumerate(slide_names, 1):
            root=ET.fromstring(z.read(slide_path))
            rels=read_rels(z, f'ppt/slides/_rels/slide{idx}.xml.rels')
            buttons=[]
            loop_videos=[]
            used_ids=set()
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
                has_explicit_action = '|' in text
                display_text, action_text, split_warnings = split_button_action_text(text)
                parsed_action, parse_warnings = parse_button_action(action_text, videos)
                parse_warnings = split_warnings + parse_warnings
                if link and not has_explicit_action and parsed_action.get('kind') in ('unresolved', 'invalid'):
                    parsed_action = None
                    parse_warnings = []
                for warning in parse_warnings:
                    match_warnings.append({'slide': f'slide{idx}', 'label': text, 'message': warning})
                video_name = parsed_action.get('target') if parsed_action and parsed_action.get('kind') == 'video' else None
                if is_loop_placeholder(action_text, video_name, link, rect, (src_w, src_h)):
                    loop_videos.append({
                        'id': unique_id(display_text, used_ids), 'label': display_text, 'raw_text': text,
                        'display_text': display_text, 'action_text': action_text,
                        'parsed_action': parsed_action, 'parse_warnings': parse_warnings,
                        'rect_emu': rect,
                        'video_file': video_name,
                    })
                    continue
                parsed_is_button = parsed_action and parsed_action.get('kind') not in ('unresolved', 'invalid')
                button_shape = looks_like_button_shape(sp, rect)
                action = (
                    parsed_action
                    if parsed_is_button else
                    (link or (parsed_action if button_shape and parsed_action else None))
                )
                if action:
                    buttons.append({
                        'id': unique_id(display_text, used_ids), 'label': display_text, 'rect_emu': rect,
                        'raw_text': text,
                        'display_text': display_text,
                        'action_text': action_text,
                        'link_action': link,
                        'parsed_action': parsed_action,
                        'parse_warnings': parse_warnings,
                        'action': action,
                    })
                if title is None and not link and not parsed_is_button and not button_shape:
                    title=text
            slides.append({'id':f'slide{idx}', 'title':title or f'Slide {idx}', 'texts':texts, 'buttons':buttons, 'loop_videos': loop_videos})
    model = {'source': str(pptx), 'slides': slides, 'source_size_emu':[src_w,src_h], 'videos': videos, 'subtitles': subtitles, 'match_warnings': match_warnings}
    resolve_slide_action_targets(model)
    repair_conflicting_slide_links(model)
    return model


def assign_video_actions(model):
    video_buttons=[]
    loop_actions=[]
    seen={}
    next_playlist=1
    def ensure_video(target):
        nonlocal next_playlist
        if target not in seen:
            seen[target]={
                'video_file': target,
                'playlist_id': f'{next_playlist:05d}',
                'title_number': next_playlist,
                'encoded_m2ts': f'build/bluray-media/encoded/{Path(target).stem}.m2ts'
            }
            next_playlist += 1
        return seen[target]
    for slide in model['slides']:
        for btn in slide['buttons']:
            act=btn['action']
            if act['kind'] != 'video':
                continue
            target=act['target']
            ensure_video(target)
            act.update(seen[target])
            video_buttons.append({
                'slide': slide['id'],
                'button': btn['label'],
                'kind': 'button',
                'start_time_seconds': act.get('start_time_seconds', 0),
                'start_timecode': act.get('start_timecode', '00:00:00'),
                'chapter_name': act.get('chapter_name'),
                **seen[target]
            })
        if slide.get('menu_loop_video'):
            info = ensure_video(slide['menu_loop_video'])
            loop = slide.setdefault('menu_loop_action', {'label': f"{slide['id']} menu loop"})
            loop.update(info)
            loop_actions.append({
                'slide': slide['id'],
                'button': loop['label'],
                'kind': 'loop',
                **info,
            })
    model['video_actions']=video_buttons
    model['loop_actions']=loop_actions


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


def loop_rect_px(model, loop, target=(1920,1080)):
    src_w, src_h = model['source_size_emu']
    sx, sy = target[0]/src_w, target[1]/src_h
    r=loop['rect_emu']
    x,y,w,h = round(r['x']*sx), round(r['y']*sy), round(r['w']*sx), round(r['h']*sy)
    x = max(0, min(target[0] - 1, x)); y = max(0, min(target[1] - 1, y))
    w = max(1, min(target[0] - x, w)); h = max(1, min(target[1] - y, h))
    return {'x':x,'y':y,'w':w,'h':h}


def generate_loop_source_videos(model, project_dir: Path, assets: Path, target=(1920,1080), seconds=30):
    loop_dir = project_dir / 'build' / 'pptx-menu-loops'
    loop_sources = set()
    for slide in model['slides']:
        loops = slide.get('loop_videos') or []
        if not loops:
            continue
        loop_dir.mkdir(parents=True, exist_ok=True)
        out = loop_dir / f"{slide['id']}_menu_loop.mp4"
        bg = assets / f"{slide['id']}_bg.png"
        cmd = ['ffmpeg', '-hide_banner', '-y', '-loop', '1', '-i', str(bg)]
        for loop in loops:
            loop['rect_px'] = loop_rect_px(model, loop, target)
            loop_sources.add(loop['video_file'])
            cmd += ['-stream_loop', '-1', '-i', str(project_dir / loop['video_file'])]
        cmd += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000']
        filters=[f'[0:v]scale={target[0]}:{target[1]},format=yuv420p[base]']
        current='base'
        for i, loop in enumerate(loops, 1):
            r=loop['rect_px']
            filters.append(f'[{i}:v]setpts=PTS-STARTPTS,scale={r["w"]}:{r["h"]}:force_original_aspect_ratio=increase,crop={r["w"]}:{r["h"]},format=yuv420p[v{i}]')
            out_label=f'vout{i}'
            filters.append(f'[{current}][v{i}]overlay={r["x"]}:{r["y"]}:shortest=0[{out_label}]')
            current=out_label
        cmd += [
            '-filter_complex', ';'.join(filters),
            '-map', f'[{current}]', '-map', f'{len(loops)+1}:a:0', '-t', str(seconds),
            '-r', '24000/1001', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-shortest', str(out)
        ]
        subprocess.run(cmd, check=True)
        slide['menu_loop_video'] = str(out.relative_to(project_dir))
    if loop_sources:
        loop_dir.mkdir(parents=True, exist_ok=True)
        (loop_dir / 'source-videos.json').write_text(json.dumps(sorted(loop_sources), indent=2) + '\n')


def draw_overlays(model, assets: Path, target=(1920,1080)):
    src_w, src_h = model['source_size_emu']
    sx, sy = target[0]/src_w, target[1]/src_h
    for slide in model['slides']:
        bg = Image.open(assets / f"{slide['id']}_bg.png").convert('RGBA')
        original_bg = bg.copy()
        loop_rects = []
        for loop in slide.get('loop_videos', []):
            r=loop.get('rect_px') or loop_rect_px(model, loop, target)
            x,y,w,h = r['x'], r['y'], r['w'], r['h']
            loop['rect_px']={'x':x,'y':y,'w':w,'h':h}
            loop_rects.append((x, y, x + w, y + h))
            # Replace the PowerPoint placeholder shape with a transparent video
            # window.  The looped playlist plays as the bottom layer on the BD
            # video plane behind this GRIN graphics layer.
            cut=Image.new('RGBA', (w, h), (0, 0, 0, 0))
            bg.paste(cut, (x, y))
        bg.save(assets / f"{slide['id']}_bg.png")
        for btn in slide['buttons']:
            r=btn['rect_emu']
            x,y,w,h = round(r['x']*sx), round(r['y']*sy), round(r['w']*sx), round(r['h']*sy)
            # PowerPoint text boxes can report a very thin shape even when the
            # rendered text is much taller.  Inflate tiny hitboxes/overlays so
            # remote/mouse activation and selection highlights remain usable.
            min_w, min_h = 48, 36
            if w < min_w:
                grow = min_w - w
                x -= grow // 2
                w = min_w
            if h < min_h:
                grow = min_h - h
                y -= grow // 2
                h = min_h
            x = max(0, min(target[0] - 1, x))
            y = max(0, min(target[1] - 1, y))
            w = max(1, min(target[0] - x, w))
            h = max(1, min(target[1] - y, h))
            btn['rect_px']={'x':x,'y':y,'w':w,'h':h}
            pad=8
            crop_box=(max(0,x-pad), max(0,y-pad), min(target[0],x+w+pad), min(target[1],y+h+pad))
            if any(not (x + w <= lx1 or x >= lx2 or y + h <= ly1 or y >= ly2) for lx1, ly1, lx2, ly2 in loop_rects):
                # If a loop placeholder sits underneath a button, the transparent
                # video window would otherwise erase the button's normal state.
                # Re-add that button crop as a fixed graphic above the video
                # plane, while selected/activated states still draw on top.
                btn['normal_overlay'] = True
                normal=Image.new('RGBA',(w+pad*2,h+pad*2),(0,0,0,0))
                crop=original_bg.crop(crop_box)
                normal.paste(crop,(crop_box[0]-(x-pad), crop_box[1]-(y-pad)))
                normal.save(assets/f"{slide['id']}_{btn['id']}_normal.png")
            for state, outline in [('selected',(255,255,255,245)),('activated',(64,255,170,255))]:
                # Build the state image as an opaque crop from the rendered slide,
                # then draw only a border.  Some BD-J/libbluray paths don't handle
                # alpha-only overlay PNGs reliably; opaque crops preserve the exact
                # PowerPoint button text/art instead of covering it.
                im=Image.new('RGBA',(w+pad*2,h+pad*2),(0,0,0,255))
                crop=original_bg.crop(crop_box) if btn.get('normal_overlay') else bg.crop(crop_box)
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


def add_neutral_menu_metadata(model, assets: Path, target=(1920,1080)):
    """Decorate the extracted PPTX model with backend-neutral authoring fields."""
    model['schema_version'] = 'auto-bluray-menu-model-v1'
    model['model_kind'] = 'backend_neutral_menu'
    model['coordinate_spaces'] = {
        'source_emu': {'width': model['source_size_emu'][0], 'height': model['source_size_emu'][1]},
        'rendered_px': {'width': target[0], 'height': target[1]},
    }
    playlists = {}
    for slide in model.get('slides', []):
        sid = slide['id']
        bg_rel = f'assets/{sid}_bg.png'
        slide['background'] = {'file': bg_rel, 'width': target[0], 'height': target[1], 'kind': 'static_image'}
        grid = button_grid(slide.get('buttons', []))
        focus_order = [btn['id'] for row in grid for btn in row]
        slide['focus_order'] = focus_order
        for index, btn in enumerate(slide.get('buttons', []), 1):
            btn['hitbox_emu'] = btn.get('rect_emu')
            btn['hitbox_px'] = btn.get('rect_px')
            btn['focus_index'] = focus_order.index(btn['id']) + 1 if btn['id'] in focus_order else index
            action = btn.get('action') or {}
            action.setdefault('type', 'play_title' if action.get('kind') == 'video' else 'go_to_menu' if action.get('kind') == 'slide' else action.get('kind', 'unknown'))
            if action.get('kind') == 'video':
                action.setdefault('video_target', action.get('target'))
                action.setdefault('playlist', action.get('playlist_id'))
                playlists[action.get('playlist_id')] = {
                    'playlist_id': action.get('playlist_id'),
                    'title_number': action.get('title_number'),
                    'video_file': action.get('video_file') or action.get('target'),
                    'encoded_m2ts': action.get('encoded_m2ts'),
                    'kind': 'title',
                }
            elif action.get('kind') == 'slide':
                action.setdefault('menu_target', action.get('target'))
        if slide.get('menu_loop_action'):
            loop = slide['menu_loop_action']
            playlists[loop.get('playlist_id')] = {
                'playlist_id': loop.get('playlist_id'),
                'title_number': loop.get('title_number'),
                'video_file': loop.get('video_file'),
                'encoded_m2ts': loop.get('encoded_m2ts'),
                'kind': 'menu_loop',
            }
    model['playlists'] = [p for _, p in sorted(playlists.items()) if p.get('playlist_id')]
    if analyze_menu_compatibility:
        report = analyze_menu_compatibility(model)
        model['feature_requirements'] = report['safe_features'] + report['bdj_required_features'] + report['unsupported_features']
        model['backend_compatibility'] = report
    else:
        model.setdefault('feature_requirements', [])
    return model


def generate_show(model, out: Path):
    lines=['# Generated from PowerPoint by tools/pptx_menu_converter.py','show','']
    lines += [
        'java_generated_class PptxMenuCommands [[',
        '    import com.hdcookbook.grin.Show;',
        '    import com.hdcookbook.grin.util.Debug;',
        '    import javax.media.Control;',
        '    import javax.media.ControllerEvent;',
        '    import javax.media.ControllerListener;',
        '    import javax.media.EndOfMediaEvent;',
        '    import javax.media.Manager;',
        '    import javax.media.Player;',
        '    import javax.media.Time;',
        '    import org.bluray.media.PlayListChangeControl;',
        '    import org.bluray.net.BDLocator;',
        '    import org.davic.media.MediaLocator;',
        '    public class PptxMenuCommands extends com.hdcookbook.grin.GrinXHelper implements ControllerListener {',
        '        private static Player player;',
        '        private static PlayListChangeControl playlistControl;',
        '        private static String returnSegment = "S:Initialize";',
        '        private static boolean loopingMenuVideo = false;',
        '        private static String currentLoopPlaylist = "";',
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
        '        public synchronized void playVideo(String videoFile, String playlistId, String menuSegment, long startSeconds) {',
        '            Debug.println("PPTX_MENU_PLAY video=" + videoFile + " playlist=" + playlistId + " start=" + startSeconds);',
        '            try {',
        '                loopingMenuVideo = false;',
        '                currentLoopPlaylist = "";',
        '                returnSegment = menuSegment;',
        '                GrinDriverXlet.hideMenuGraphics();',
        '                BDLocator loc = new BDLocator("bd://1.PLAYLIST:" + playlistId);',
        '                if (player == null) {',
        '                    player = Manager.createPlayer(new MediaLocator(loc));',
        '                    player.addControllerListener(this);',
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
        '                    player.addControllerListener(this);',
        '                    player.prefetch();',
        '                }',
        '                if (startSeconds > 0) { player.setMediaTime(new Time((double) startSeconds)); }',
        '                player.start();',
        '            } catch (Throwable t) {',
        '                Debug.println("PPTX_MENU_PLAY_FAILED video=" + videoFile + " playlist=" + playlistId);',
        '                if (Debug.LEVEL > 0) { Debug.printStackTrace(t); }',
        '            }',
        '        }',
        '        public synchronized void playMenuLoop(String videoFile, String playlistId) {',
        '            if (playlistId != null && playlistId.equals(currentLoopPlaylist) && loopingMenuVideo) { return; }',
        '            Debug.println("PPTX_MENU_LOOP video=" + videoFile + " playlist=" + playlistId);',
        '            try {',
        '                loopingMenuVideo = true;',
        '                currentLoopPlaylist = playlistId;',
        '                BDLocator loc = new BDLocator("bd://1.PLAYLIST:" + playlistId);',
        '                if (player == null) {',
        '                    player = Manager.createPlayer(new MediaLocator(loc));',
        '                    player.addControllerListener(this);',
        '                    player.prefetch();',
        '                    Control[] controls = player.getControls();',
        '                    for (int i = 0; i < controls.length; i++) {',
        '                        if (controls[i] instanceof PlayListChangeControl) { playlistControl = (PlayListChangeControl) controls[i]; }',
        '                    }',
        '                } else if (playlistControl != null) {',
        '                    player.stop();',
        '                    playlistControl.selectPlayList(loc);',
        '                } else {',
        '                    player.stop();',
        '                    player = Manager.createPlayer(new MediaLocator(loc));',
        '                    player.addControllerListener(this);',
        '                    player.prefetch();',
        '                }',
        '                player.start();',
        '            } catch (Throwable t) {',
        '                Debug.println("PPTX_MENU_LOOP_FAILED video=" + videoFile + " playlist=" + playlistId);',
        '                if (Debug.LEVEL > 0) { Debug.printStackTrace(t); }',
        '            }',
        '        }',
        '        public synchronized void stopMenuLoop() {',
        '            try {',
        '                if (loopingMenuVideo && player != null) { player.stop(); }',
        '            } catch (Throwable ignored) { }',
        '            loopingMenuVideo = false;',
        '            currentLoopPlaylist = "";',
        '        }',
        '        public void controllerUpdate(ControllerEvent event) {',
        '            if (event instanceof EndOfMediaEvent) {',
        '                if (loopingMenuVideo) {',
        '                    Debug.println("PPTX_MENU_LOOP_RESTART playlist=" + currentLoopPlaylist);',
        '                    try { if (player != null) { player.stop(); player.setMediaTime(new Time(0)); player.start(); } } catch (Throwable ignored) { }',
        '                    return;',
        '                }',
        '                Debug.println("PPTX_MENU_END_RETURN segment=" + returnSegment);',
        '                try { if (player != null) { player.stop(); } } catch (Throwable ignored) { }',
        '                GrinDriverXlet.showMenuSegment(returnSegment);',
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
        '    setup {', f'        F:{first}.BG', '    } setup_done {', f'        activate_segment S:{first}.Enter ;', '    }',';',''
    ]
    for slide in model['slides']:
        sid=slide['id']
        loop = slide.get('menu_loop_action')
        normal_features = [f'        F:{sid}.{btn["id"]}.Normal' for btn in slide['buttons'] if btn.get('normal_overlay')]
        setup_done = []
        if loop:
            video=(loop.get('video_file') or '').replace('\\', '\\\\').replace('"', '\\"')
            playlist=loop.get('playlist_id', '00000')
            setup_done.append(f'        java_command [[ playMenuLoop("{video}", "{playlist}"); ]]')
        else:
            setup_done.append('        java_command [[ stopMenuLoop(); ]]')
        lines += [f'segment S:{sid}.Enter','    setup {',f'        F:{sid}.BG',*normal_features,f'        F:{sid}.Buttons','    } setup_done {',*setup_done,f'        activate_segment S:{sid} ;','    }',';','']
        lines += [f'segment S:{sid}','    active {',f'        F:{sid}.BG',*normal_features,f'        F:{sid}.Buttons','    } setup {',f'        F:{sid}.BG',*normal_features,f'        F:{sid}.Buttons','    } rc_handlers {',f'        R:{sid}','    }',';','']
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
            if btn.get('normal_overlay'):
                lines.append(f'feature fixed_image F:{sid}.{bid}.Normal {x} {y} "assets/{sid}_{bid}_normal.png" ;')
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
                target = act.get('target') or first
                lines.append(f"        {bid} {bid}_activated {{ activate_segment S:{target}.Enter ; }}")
            elif act['kind']=='video':
                video=act['target'].replace('\\', '\\\\').replace('"', '\\"')
                playlist=act.get('playlist_id', '00000')
                start=int(act.get('start_time_seconds') or 0)
                lines.append(f"        {bid} {bid}_activated {{ activate_segment S:VideoPlayback ; sync_display ; java_command [[ playVideo(\"{video}\", \"{playlist}\", \"S:{sid}.Enter\", {start}); ]] }}")
            elif act['kind']=='builtin':
                name = act.get('name') or act.get('type')
                if name in ('main', 'top_menu'):
                    lines.append(f"        {bid} {bid}_activated {{ activate_segment S:{first}.Enter ; }}")
                elif name in ('disabled', 'none'):
                    lines.append(f"        {bid} {bid}_activated {{ }}")
                else:
                    # Parsed Grammar v1 built-ins that require runtime state are
                    # carried in the neutral model until final behavior lands.
                    lines.append(f"        {bid} {bid}_activated {{ java_command [[ stopMenuLoop(); ]] }}")
            else:
                # Grammar v1 can parse built-in commands before every command has
                # final BD-J/HDMV behavior.  Keep generated menus buildable while
                # the neutral model carries the parsed command metadata.
                lines.append(f"        {bid} {bid}_activated {{ java_command [[ stopMenuLoop(); ]] }}")
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
    (out/'README.md').write_text(f'''# PptxMenu — generated from project PPTX

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
    pptx=find_project_pptx(project_dir)
    if pptx is None:
        pptx=project_dir/'menu.pptx'
        generate_menu_pptx_from_template(project_dir, pptx)
    if out.exists(): shutil.rmtree(out)
    (out/'assets').mkdir(parents=True)
    model=extract_slide_model(pptx, project_dir)
    export_slide_pngs(pptx, out/'assets')
    generate_loop_source_videos(model, project_dir, out/'assets')
    assign_video_actions(model)
    draw_overlays(model, out/'assets')
    add_neutral_menu_metadata(model, out/'assets')
    # Emit the backend-neutral model before any backend-specific GRIN/BD-J files.
    (out/'menu-model.json').write_text(json.dumps(model, indent=2)+'\n')
    generate_show(model, out)
    write_build_files(out, model)
    (out/'menu-model.json').write_text(json.dumps(model, indent=2)+'\n')
    if write_compatibility_report:
        write_compatibility_report(out, model)
        (out/'menu-model.json').write_text(json.dumps(model, indent=2)+'\n')
    if write_html_menu_preview:
        preview_path = project_dir/'menu-preview.html'
        write_html_menu_preview(out/'menu-model.json', preview_path, project_dir)
        shutil.copy2(preview_path, out/'menu-preview.html')
        if os.environ.get('AUTO_BLURAY_NO_PREVIEW_OPEN') != '1':
            try:
                webbrowser.open(preview_path.resolve().as_uri())
            except Exception as exc:
                print(f'Warning: could not auto-open menu preview: {exc}', file=sys.stderr)
    (out/'video-actions.json').write_text(json.dumps((model.get('video_actions', []) + model.get('loop_actions', [])), indent=2)+'\n')
    (out/'loop-actions.json').write_text(json.dumps(model.get('loop_actions', []), indent=2)+'\n')
    print(f'Generated {out}')
    print(f"Slides: {len(model['slides'])}; buttons: {sum(len(s['buttons']) for s in model['slides'])}")

if __name__=='__main__': main()
