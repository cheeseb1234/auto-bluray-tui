from __future__ import annotations

import unittest
from pathlib import Path


class PublicPathHygieneTests(unittest.TestCase):
    def test_public_surfaces_do_not_embed_personal_paths(self):
        root = Path(__file__).resolve().parents[1]
        public_files = [
            *root.glob('README*.md'),
            *root.glob('scripts/*.sh'),
            *root.glob('tools/*.py'),
        ]

        forbidden_home = '/' + 'home' + '/' + 'corey'
        forbidden_project = forbidden_home + '/' + '.openclaw' + '/' + 'Bluray project'
        offenders: list[str] = []

        for path in sorted(public_files):
            text = path.read_text(encoding='utf-8')
            if forbidden_project in text or forbidden_home in text:
                offenders.append(str(path.relative_to(root)))

        self.assertEqual(offenders, [], f'personal path references found in public files: {offenders}')


if __name__ == '__main__':
    unittest.main()
