#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import pptx_menu_converter


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if len(argv) < 3:
        print('usage: pptx_menu_project.py <find|generate> PROJECT_DIR [MENU_PATH]', file=sys.stderr)
        return 2

    command = argv[1]
    project = Path(argv[2]).resolve()

    if command == 'find':
        menu = pptx_menu_converter.find_project_pptx(project)
        print(menu if menu else '')
        return 0

    if command == 'generate':
        if len(argv) != 4:
            print('usage: pptx_menu_project.py generate PROJECT_DIR MENU_PATH', file=sys.stderr)
            return 2
        menu = Path(argv[3]).resolve()
        pptx_menu_converter.generate_menu_pptx_from_template(project, menu)
        print(menu)
        return 0

    print(f'unknown command: {command}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
