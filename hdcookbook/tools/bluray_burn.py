#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SECTOR_SIZE = 2048


def which(name: str):
    root = Path(__file__).resolve().parents[1]
    local = root / 'tools' / 'bin' / name
    if local.exists():
        return str(local)
    return shutil.which(name)


def detect_burners():
    burners = []
    for dev in sorted(Path('/dev').glob('sr*')):
        name = dev.name
        vendor = ''
        model = ''
        try:
            vendor = (Path('/sys/block') / name / 'device/vendor').read_text(errors='ignore').strip()
        except Exception:
            pass
        try:
            model = (Path('/sys/block') / name / 'device/model').read_text(errors='ignore').strip()
        except Exception:
            pass
        burners.append({'device': str(dev), 'label': ' '.join(x for x in (vendor, model) if x).strip() or name})
    return burners


def media_space(xorriso: str, device: str):
    result = subprocess.run(
        [xorriso, '-outdev', device, '-tell_media_space', '-toc'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
    )
    text = result.stdout or ''
    # xorriso normally prints: "Media space  : 12219392s"
    matches = re.findall(r'(?:Media|Free) space\s*:?\s*([0-9]+)s', text, re.IGNORECASE)
    sectors = max([int(m) for m in matches], default=0)
    blankish = bool(re.search(r'Media status\s*:?\s*(is )?(blank|appendable|overwriteable|formatted)', text, re.IGNORECASE))
    return {
        'returncode': result.returncode,
        'sectors': sectors,
        'bytes': sectors * SECTOR_SIZE,
        'blankish': blankish,
        'raw': text[-4000:],
    }


def choose_ready_burner(xorriso: str, iso: Path, preferred: str | None = None):
    iso_size = iso.stat().st_size
    burners = detect_burners()
    if preferred:
        burners = sorted(burners, key=lambda b: 0 if b['device'] == preferred else 1)
    checked = []
    for burner in burners:
        info = media_space(xorriso, burner['device'])
        burner = {**burner, **info}
        burner['enough_space'] = info['bytes'] >= iso_size
        checked.append(burner)
        if burner['enough_space'] and burner['blankish']:
            return burner, checked
    return None, checked


def burn(xorriso: str, device: str, iso: Path):
    cmd = [xorriso, '-as', 'cdrecord', '-v', f'dev={device}', '-eject', str(iso)]
    print('+', ' '.join(cmd), flush=True)
    return subprocess.run(cmd, check=True).returncode


def main():
    ap = argparse.ArgumentParser(description='Detect Blu-ray burner/media and burn final ISO when safe.')
    ap.add_argument('iso')
    ap.add_argument('--device', default=None)
    ap.add_argument('--auto', action='store_true', help='burn automatically only if a detected burner has enough blank/appendable space')
    ap.add_argument('--status-json', action='store_true')
    args = ap.parse_args()

    iso = Path(args.iso).resolve()
    if not iso.exists():
        raise SystemExit(f'Missing ISO: {iso}')
    xorriso = which('xorriso')
    if not xorriso:
        raise SystemExit('Missing xorriso')

    ready, checked = choose_ready_burner(xorriso, iso, args.device)
    status = {'iso': str(iso), 'iso_bytes': iso.stat().st_size, 'burners': checked, 'ready_device': ready['device'] if ready else None}
    if args.status_json:
        print(json.dumps(status, indent=2))
        return 0 if ready else 2

    if args.auto:
        print(json.dumps(status, indent=2), flush=True)
        if not ready:
            raise SystemExit('No burner with blank/appendable media large enough for ISO was detected; skipping automatic burn.')
        burn(xorriso, ready['device'], iso)
        print('Burn complete. Insert another blank disc and use the TUI burn command for additional copies, or exit.', flush=True)
        return 0

    device = args.device or (ready['device'] if ready else None)
    if not device:
        raise SystemExit('No suitable burner detected')
    burn(xorriso, device, iso)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
