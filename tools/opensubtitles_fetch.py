#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import os
import re
import struct
import time
import urllib.parse
import zipfile
from pathlib import Path

import requests

VIDEO_EXTS = {'.mkv', '.mp4', '.m2ts', '.mov'}
SUB_EXTS = {'.srt', '.sup', '.ass', '.ssa'}
API_ROOT = 'https://api.opensubtitles.com/api/v1'
USER_AGENT = 'AutoBluRayTUI v1.0'


def existing_sidecars(project: Path, video: Path):
    stem = video.stem.lower()
    rows = []
    for p in project.iterdir():
        if p.suffix.lower() in SUB_EXTS and p.stem.lower().startswith(stem):
            rows.append(p)
    return rows


def opensubtitles_hash(path: Path):
    size = path.stat().st_size
    if size < 131072:
        return None
    total = size
    with path.open('rb') as f:
        for _ in range(8192):
            data = f.read(8)
            if len(data) < 8:
                return None
            total = (total + struct.unpack('<Q', data)[0]) & 0xFFFFFFFFFFFFFFFF
        f.seek(max(0, size - 65536))
        for _ in range(8192):
            data = f.read(8)
            if len(data) < 8:
                return None
            total = (total + struct.unpack('<Q', data)[0]) & 0xFFFFFFFFFFFFFFFF
    return f'{total:016x}'


def clean_query(stem: str):
    text = re.sub(r'[._]+', ' ', stem)
    text = re.sub(r'\b(2160p|1080p|720p|4k|uhd|bluray|blu ray|remux|x264|x265|h264|h265|hevc|aac|ac3|dts|truehd)\b', ' ', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip()
    return text or stem


def headers(api_key: str, token: str | None = None):
    h = {'Api-Key': api_key, 'User-Agent': USER_AGENT, 'Accept': 'application/json'}
    if token:
        h['Authorization'] = 'Bearer ' + token
    return h


def login(session: requests.Session, api_key: str, username: str | None, password: str | None):
    if not username or not password:
        return None, API_ROOT
    r = session.post(API_ROOT + '/login', headers={**headers(api_key), 'Content-Type': 'application/json'}, json={'username': username, 'password': password}, timeout=30)
    r.raise_for_status()
    data = r.json()
    base_url = data.get('base_url') or 'api.opensubtitles.com'
    if not base_url.startswith('http'):
        base_url = 'https://' + base_url + '/api/v1'
    return data.get('token'), base_url.rstrip('/')


def search(session: requests.Session, base_url: str, api_key: str, token: str | None, video: Path, language: str):
    movie_hash = opensubtitles_hash(video)
    params = {
        'languages': language,
        'query': clean_query(video.stem),
        'moviebytesize': str(video.stat().st_size),
        'order_by': 'download_count',
        'order_direction': 'desc',
    }
    if movie_hash:
        params['moviehash'] = movie_hash
    r = session.get(base_url + '/subtitles', headers=headers(api_key, token), params=params, timeout=30)
    r.raise_for_status()
    data = r.json().get('data') or []
    scored = []
    for row in data:
        attrs = row.get('attributes') or {}
        files = attrs.get('files') or []
        if not files:
            continue
        score = 0
        if movie_hash and (attrs.get('moviehash_match') or attrs.get('movie_hash_match')):
            score += 1000
        if attrs.get('language') == language:
            score += 100
        if not attrs.get('hearing_impaired'):
            score += 25
        with contextlib.suppress(Exception):
            score += min(50, int(attrs.get('download_count') or 0) // 100)
        with contextlib.suppress(Exception):
            score += float(attrs.get('ratings') or 0)
        scored.append((score, row, files[0]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0] if scored else None


def download_subtitle(session: requests.Session, base_url: str, api_key: str, token: str | None, file_id: int, dest: Path):
    if not token:
        raise RuntimeError('OpenSubtitles download requires OPENSUBTITLES_USERNAME and OPENSUBTITLES_PASSWORD')
    r = session.post(base_url + '/download', headers={**headers(api_key, token), 'Content-Type': 'application/json'}, json={'file_id': file_id, 'sub_format': 'srt'}, timeout=30)
    r.raise_for_status()
    link = r.json().get('link')
    if not link:
        raise RuntimeError('OpenSubtitles download response did not include a link')
    d = session.get(link, headers={'User-Agent': USER_AGENT}, timeout=60)
    d.raise_for_status()
    content = d.content
    ctype = d.headers.get('content-type', '').lower()
    name = urllib.parse.urlparse(link).path.lower()
    if content[:2] == b'\x1f\x8b' or name.endswith('.gz'):
        content = gzip.decompress(content)
    elif name.endswith('.zip') or 'zip' in ctype:
        with zipfile.ZipFile(__import__('io').BytesIO(content)) as z:
            member = next((n for n in z.namelist() if n.lower().endswith('.srt')), None)
            if not member:
                raise RuntimeError('Downloaded zip did not contain an .srt file')
            content = z.read(member)
    dest.write_bytes(content)


def main():
    ap = argparse.ArgumentParser(description='Fetch missing sidecar subtitles from OpenSubtitles.com for a Blu-ray project.')
    ap.add_argument('project_dir')
    ap.add_argument('--language', default=os.environ.get('OPENSUBTITLES_LANGUAGE', 'en'), help='OpenSubtitles language code, default en')
    ap.add_argument('--force', action='store_true', help='download even when a matching sidecar already exists')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    api_key = os.environ.get('OPENSUBTITLES_API_KEY')
    username = os.environ.get('OPENSUBTITLES_USERNAME')
    password = os.environ.get('OPENSUBTITLES_PASSWORD')
    report = {'project_dir': str(project), 'language': args.language, 'status': 'ok', 'videos': []}

    videos = sorted([p for p in project.iterdir() if p.suffix.lower() in VIDEO_EXTS], key=lambda p: p.name.lower())
    if not api_key:
        report.update({'status': 'skipped', 'message': 'OPENSUBTITLES_API_KEY is not set; skipping subtitle lookup'})
        print(json.dumps(report, indent=2))
        return 0
    if not username or not password:
        report.update({'status': 'skipped', 'message': 'OPENSUBTITLES_USERNAME/PASSWORD are not set; downloads require an OpenSubtitles login'})
        print(json.dumps(report, indent=2))
        return 0

    session = requests.Session()
    try:
        token, base_url = login(session, api_key, username, password)
    except Exception as e:
        report.update({'status': 'skipped', 'message': f'OpenSubtitles login failed: {e}'})
        print(json.dumps(report, indent=2))
        return 0

    for video in videos:
        row = {'video': video.name, 'existing': [p.name for p in existing_sidecars(project, video)]}
        if row['existing'] and not args.force:
            row['status'] = 'kept-existing'
            report['videos'].append(row)
            continue
        try:
            hit = search(session, base_url, api_key, token, video, args.language)
            if not hit:
                row['status'] = 'not-found'
            else:
                score, sub_row, file_row = hit
                attrs = sub_row.get('attributes') or {}
                file_id = file_row.get('file_id')
                dest = project / f'{video.stem}.{args.language}.srt'
                row.update({'status': 'found', 'score': score, 'subtitle_id': sub_row.get('id'), 'file_id': file_id, 'release': attrs.get('release'), 'dest': dest.name})
                if not args.dry_run:
                    download_subtitle(session, base_url, api_key, token, int(file_id), dest)
                    row['status'] = 'downloaded'
            report['videos'].append(row)
            time.sleep(1.05)  # respect OpenSubtitles' conservative API pacing
        except Exception as e:
            row.update({'status': 'error', 'message': str(e)})
            report['videos'].append(row)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
