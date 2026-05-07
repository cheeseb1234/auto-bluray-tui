from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

import pptx_menu_converter


class PptxMenuConverterTests(unittest.TestCase):
    def test_export_slide_pngs_requires_libreoffice_or_soffice(self):
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / 'menu.pptx'
            pptx.write_text('fake')
            out = Path(tmp) / 'assets'
            with mock.patch.object(pptx_menu_converter.shutil, 'which', return_value=None):
                with self.assertRaises(SystemExit) as caught:
                    pptx_menu_converter.export_slide_pngs(pptx, out)
        self.assertIn('LibreOffice/soffice', str(caught.exception))

    def test_export_slide_pngs_requires_pdftoppm(self):
        with tempfile.TemporaryDirectory() as tmp:
            pptx = Path(tmp) / 'menu.pptx'
            pptx.write_text('fake')
            out = Path(tmp) / 'assets'

            def fake_which(name: str):
                if name == 'soffice':
                    return '/tmp/soffice'
                return None

            with mock.patch.object(pptx_menu_converter.shutil, 'which', side_effect=fake_which):
                with self.assertRaises(SystemExit) as caught:
                    pptx_menu_converter.export_slide_pngs(pptx, out)
        self.assertIn('pdftoppm', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
