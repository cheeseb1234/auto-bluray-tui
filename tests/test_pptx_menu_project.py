from __future__ import annotations

import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import pptx_menu_project


class PptxMenuProjectTests(unittest.TestCase):
    def test_find_prints_blank_when_no_menu_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            out = StringIO()
            with mock.patch('sys.stdout', out):
                rc = pptx_menu_project.main(['pptx_menu_project.py', 'find', str(project)])
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue(), '\n')

    def test_generate_dispatches_to_converter(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            menu = project / 'menu.pptx'
            with mock.patch.object(pptx_menu_project.pptx_menu_converter, 'generate_menu_pptx_from_template') as gen:
                rc = pptx_menu_project.main(['pptx_menu_project.py', 'generate', str(project), str(menu)])
        self.assertEqual(rc, 0)
        gen.assert_called_once_with(project.resolve(), menu.resolve())


if __name__ == '__main__':
    unittest.main()
