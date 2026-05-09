#!/usr/bin/env python3
"""PowerPoint button action grammar for Auto Blu-ray TUI.

Grammar v1 intentionally stays human-readable.  It supports simple action text
on a PowerPoint button, or preferred display/action text split by a pipe:

    Button Text | Action

This module is pure parser logic so PPTX extraction, BD-J generation, and HDMV
compatibility can all consume the same normalized action objects.
"""
from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

VIDEO_EXTS = ('.mp4', '.mkv', '.m2ts', '.mov')
NOISE_WORDS = {
    '4k', 'uhd', '1080p', '720p', 'bluray', 'blu', 'ray', 'bd', 'remux',
    'x264', 'x265', 'h264', 'h265', 'hevc', 'aac', 'ac3', 'dts', 'truehd',
    'proper', 'repack', 'extended', 'theatrical', 'despecialized', 'edition',
}
BUILTIN_ACTIONS = {'main', 'back', 'top menu', 'resume', 'replay', 'play all', 'disabled', 'none'}
SLIDE_PREFIXES = ('goto:', 'menu:', 'slide:')


def match_key(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', (value or '').lower()).strip()


def relaxed_key(value: str) -> str:
    words = [w for w in match_key(value).split() if w not in NOISE_WORDS]
    return ' '.join(words)


def format_timecode(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


def parse_timestamp(value: str) -> tuple[int | None, str | None]:
    """Parse Grammar v1 timestamps into seconds and canonical HH:MM:SS.

    Accepted forms: H:MM:SS, HH:MM:SS, MM:SS, 75s, 1h00m30s.
    """
    text = (value or '').strip().lower()
    if not text:
        return None, None
    if re.fullmatch(r'\d+s', text):
        seconds = int(text[:-1])
        return seconds, format_timecode(seconds)
    duration = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?', text)
    if duration and any(duration.groups()):
        hours = int(duration.group(1) or 0)
        minutes = int(duration.group(2) or 0)
        seconds_part = int(duration.group(3) or 0)
        if minutes >= 60 or seconds_part >= 60:
            return None, None
        seconds = hours * 3600 + minutes * 60 + seconds_part
        return seconds, format_timecode(seconds)
    parts = text.split(':')
    if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
        return None, None
    nums = [int(p) for p in parts]
    if any(n >= 60 for n in nums[-2:]):
        return None, None
    seconds = nums[0] * 60 + nums[1] if len(nums) == 2 else nums[0] * 3600 + nums[1] * 60 + nums[2]
    return seconds, format_timecode(seconds)


def infer_display_text(action_text: str) -> str:
    text = ' '.join((action_text or '').split()).strip()
    if not text:
        return ''
    lower = text.lower()
    for prefix in SLIDE_PREFIXES:
        if lower.startswith(prefix):
            return text.split(':', 1)[1].strip() or text
    if lower.startswith('file:'):
        name = text.split(':', 1)[1].strip()
        return Path(name).stem if name else text
    key = match_key(text)
    if key in BUILTIN_ACTIONS:
        return ' '.join(w.capitalize() for w in key.split())
    base = text
    if '#' in base:
        base = base.rsplit('#', 1)[0].strip()
    if '@' in base:
        base = base.rsplit('@', 1)[0].strip()
    return base or text


def split_display_action(raw_text: str) -> tuple[str, str, list[str]]:
    """Return display_text, action_text, warnings from raw PowerPoint text."""
    raw = raw_text or ''
    text = ' '.join(raw.split()).strip()
    warnings: list[str] = []
    if '|' in text:
        left, right = [part.strip() for part in text.split('|', 1)]
        if not right:
            warnings.append('empty action after pipe; treating button as disabled')
            action_text = 'none'
        else:
            action_text = right
        display_text = left or infer_display_text(action_text)
        if not left:
            warnings.append('empty display text before pipe; inferred display text from action')
        return display_text, action_text, warnings
    quoted = re.match(r'^"([^"]+)"\s+(.+)$', text)
    if quoted:
        warnings.append('quoted display syntax is supported, but pipe syntax is preferred')
        return quoted.group(1).strip(), quoted.group(2).strip(), warnings
    return infer_display_text(text), text, warnings


def _unique_values(videos: dict[str, str]) -> list[str]:
    return sorted(set(videos.values()), key=str.lower)


def resolve_video_target(name: str, videos: dict[str, str], *, exact: bool = False) -> tuple[str | None, list[str]]:
    """Resolve a video target using exact or backward-compatible fuzzy matching."""
    label = (name or '').strip()
    warnings: list[str] = []
    if not label:
        return None, ['empty video target']
    if exact:
        hits = [v for v in _unique_values(videos) if v.lower() == label.lower()]
        if len(hits) == 1:
            return hits[0], warnings
        return None, [f'exact file target not found: {label}']

    exact_hit = videos.get(label.lower()) or videos.get(match_key(label))
    if exact_hit:
        return exact_hit, warnings

    relaxed = relaxed_key(label)
    relaxed_hits = sorted({name for key, name in videos.items() if relaxed and relaxed_key(key) == relaxed})
    if len(relaxed_hits) == 1:
        return relaxed_hits[0], [f'relaxed label match: "{label}" -> "{relaxed_hits[0]}"']
    if len(relaxed_hits) > 1:
        return None, [f'ambiguous video target "{label}" matches: ' + ', '.join(relaxed_hits[:8])]

    label_words = set(relaxed.split())
    subset_hits = sorted({name for key, name in videos.items() if label_words and label_words <= set(relaxed_key(key).split())})
    if len(subset_hits) == 1:
        return subset_hits[0], [f'partial label match: "{label}" -> "{subset_hits[0]}"']
    if len(subset_hits) > 1:
        return None, [f'ambiguous video target "{label}" matches: ' + ', '.join(subset_hits[:8])]

    scored = []
    for key, value in videos.items():
        if not key:
            continue
        score = max(
            difflib.SequenceMatcher(None, match_key(label), key).ratio(),
            difflib.SequenceMatcher(None, relaxed, relaxed_key(key)).ratio() if relaxed else 0,
        )
        scored.append((score, key, value))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= 0.88:
        top_score = scored[0][0]
        top_hits = sorted({value for score, _, value in scored if abs(score - top_score) < 0.001})
        second_score = scored[1][0] if len(scored) > 1 else 0
        if len(top_hits) == 1 and top_score - second_score >= 0.08:
            return scored[0][2], [f'fuzzy label match: "{label}" -> "{scored[0][2]}" ({top_score:.2f})']
        return None, [f'ambiguous video target "{label}" matches: ' + ', '.join(top_hits[:8])]
    return None, warnings


def _normalize_builtin(name: str) -> str:
    return match_key(name).replace(' ', '_')


def parse_button_action(action_text: str, videos: dict[str, str], slides: dict[str, str] | None = None, aliases: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    """Parse Grammar v1 action text into a normalized action object."""
    del aliases  # Clean extension point for future project aliases.
    text = ' '.join((action_text or '').split()).strip()
    warnings: list[str] = []
    if not text:
        return {'kind': 'builtin', 'name': 'none', 'type': 'none'}, ['empty action text; treating button as disabled']

    key = match_key(text)
    if key in BUILTIN_ACTIONS:
        name = _normalize_builtin(key)
        return {'kind': 'builtin', 'name': name, 'type': name}, warnings

    lower = text.lower()
    for prefix in SLIDE_PREFIXES:
        if lower.startswith(prefix):
            target = text.split(':', 1)[1].strip()
            if not target:
                return {'kind': 'invalid', 'raw': text}, [f'{prefix[:-1]} action is missing a slide name']
            action = {'kind': 'slide', 'target': target, 'target_label': target, 'type': 'go_to_menu'}
            if slides:
                resolved = slides.get(match_key(target))
                if resolved:
                    action['target'] = resolved
                else:
                    warnings.append(f'slide target "{target}" does not match any slide title/id')
            return action, warnings

    exact = False
    video_expr = text
    if lower.startswith('file:'):
        exact = True
        video_expr = text.split(':', 1)[1].strip()

    chapter: str | int | None = None
    video_label = video_expr
    if '#' in video_label:
        video_label, chapter_text = [part.strip() for part in video_label.rsplit('#', 1)]
        if not video_label or not chapter_text:
            return {'kind': 'invalid', 'raw': text}, [f'invalid chapter action "{text}"; expected VideoName#ChapterName']
        chapter = int(chapter_text) if chapter_text.isdigit() else chapter_text

    start_seconds = None
    start_time = None
    if '@' in video_label:
        video_label, timestamp_text = [part.strip() for part in video_label.rsplit('@', 1)]
        if not video_label or not timestamp_text:
            return {'kind': 'invalid', 'raw': text}, [f'invalid timestamp action "{text}"; expected VideoName@timestamp']
        start_seconds, start_time = parse_timestamp(timestamp_text)
        if start_seconds is None:
            return {'kind': 'invalid', 'raw': text}, [f'invalid timestamp in "{text}"']

    video_file, match_warnings = resolve_video_target(video_label, videos, exact=exact)
    warnings.extend(match_warnings)
    if not video_file:
        return {'kind': 'unresolved', 'raw': text, 'target_label': video_label}, warnings or [f'video target not found: {video_label}']

    action: dict[str, Any] = {
        'kind': 'video',
        'type': 'play_title',
        'target': video_file,
        'video_file': video_file,
    }
    if exact:
        action['exact_file'] = True
    if start_seconds is not None:
        action['start_time_seconds'] = start_seconds
        action['start_time'] = start_time
        action['start_timecode'] = start_time
    if chapter is not None:
        action['chapter'] = chapter
        if isinstance(chapter, str):
            action['chapter_name'] = chapter
        else:
            action['chapter_number'] = chapter
    return action, warnings


__all__ = [
    'BUILTIN_ACTIONS', 'SLIDE_PREFIXES', 'VIDEO_EXTS', 'infer_display_text',
    'match_key', 'relaxed_key', 'parse_timestamp', 'format_timecode',
    'split_display_action', 'parse_button_action', 'resolve_video_target',
]
